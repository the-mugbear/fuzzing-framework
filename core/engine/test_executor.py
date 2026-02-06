"""
Test Executor - Handles test case execution against targets.

This module provides the core test execution logic, managing the full lifecycle
of sending test cases to targets and processing responses.

Component Overview:
-------------------
The TestExecutor encapsulates all logic for:
- Selecting appropriate transport (ephemeral vs persistent connections)
- Sending test data and receiving responses
- Handling transport errors (timeouts, connection refused, etc.)
- Classifying responses via protocol validators
- Managing connection health for persistent connections

Key Responsibilities:
--------------------
1. Transport Management:
   - Creates ephemeral connections for simple per-test execution
   - Uses ConnectionManager for persistent/session connections
   - Properly cleans up connections after use

2. Error Handling:
   - Connection refused -> helpful Docker networking guidance
   - Timeouts -> classified as HANG results
   - Transport errors -> classified as CRASH results
   - Marks unhealthy connections for cleanup

3. Response Classification:
   - Applies protocol-specific validators when available
   - Distinguishes PASS, LOGICAL_FAILURE, CRASH, HANG results
   - Handles validator exceptions gracefully

4. Callback Integration:
   - Optional callback for connection refused handling
   - Allows orchestrator to update session state on errors

Integration Points:
------------------
- Used by FuzzingLoopCoordinator for test execution
- Uses ConnectionManager for persistent connections
- Uses TransportFactory for ephemeral connections
- Calls protocol validators via validator_provider callback

Usage Example:
-------------
    # Create executor with dependencies
    executor = TestExecutor(
        connection_manager=conn_mgr,
        validator_provider=lambda proto: plugin_manager.get_validator(proto),
    )

    # Execute test case
    result, response = await executor.execute(
        session=session,
        test_case=test_case,
        on_connection_refused=handle_connection_error,
    )

    # Classify response manually if needed
    result = executor.classify_response("my_protocol", response_bytes)

Error Handling:
--------------
The executor categorizes errors into TestCaseResult values:
- ConnectionRefusedError -> CRASH (with helpful error message)
- ConnectionTimeoutError -> HANG
- ReceiveTimeoutError -> HANG
- TransportError -> CRASH
- Other exceptions -> CRASH (logged as execution_error)

Note:
----
This module is part of the Phase 5 orchestrator decomposition. It extracts
test execution into a focused, testable component.

See Also:
--------
- core/engine/transport.py - Transport implementation
- core/engine/connection_manager.py - Persistent connection management
- core/engine/fuzzing_loop.py - Uses TestExecutor in the main loop
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Tuple, TYPE_CHECKING

import structlog

from core.config import settings
from core.exceptions import (
    TransportError,
    ConnectionRefusedError as FuzzerConnectionRefusedError,
    ConnectionTimeoutError,
    ReceiveTimeoutError,
)
from core.engine.transport import TransportFactory
from core.models import (
    FuzzSession,
    FuzzSessionStatus,
    TestCase,
    TestCaseResult,
)

if TYPE_CHECKING:
    from core.engine.connection_manager import ConnectionManager

logger = structlog.get_logger()


class TestExecutor:
    """
    Executes test cases against target systems.

    Handles:
    - Transport selection (ephemeral vs persistent connections)
    - Send/receive with proper error handling
    - Response classification via protocol validators
    - Error categorization (CRASH, HANG, LOGICAL_FAILURE)

    This component can be used standalone or integrated with the orchestrator.
    """

    def __init__(
        self,
        connection_manager: Optional["ConnectionManager"] = None,
        validator_provider: Optional[Callable[[str], Optional[Callable]]] = None,
    ):
        """
        Initialize the TestExecutor.

        Args:
            connection_manager: Optional ConnectionManager for persistent connections.
                               If None, only ephemeral connections are available.
            validator_provider: Function to get validator for a protocol.
                               Signature: (protocol_name) -> Optional[Callable[[bytes], bool]]
                               If None, no validation is performed.
        """
        self._connection_manager = connection_manager
        self._validator_provider = validator_provider

    def set_connection_manager(self, manager: "ConnectionManager") -> None:
        """Set the connection manager (for lazy initialization)."""
        self._connection_manager = manager

    async def execute(
        self,
        session: FuzzSession,
        test_case: TestCase,
        on_connection_refused: Optional[Callable[[FuzzSession, str], None]] = None,
    ) -> Tuple[TestCaseResult, Optional[bytes]]:
        """
        Execute a test case against the target.

        Args:
            session: The fuzzing session
            test_case: The test case to execute
            on_connection_refused: Optional callback for connection refused errors.
                                   Called with (session, error_message).

        Returns:
            Tuple of (result, response_bytes)
        """
        start_time = time.time()
        response: Optional[bytes] = None
        result: TestCaseResult = TestCaseResult.CRASH
        managed_transport = None

        try:
            # Choose transport based on connection mode
            if self._should_use_persistent_connection(session):
                if self._connection_manager is None:
                    raise TransportError(
                        "ConnectionManager required for persistent connections"
                    )
                managed_transport = await self._connection_manager.get_transport(session)
                transport = managed_transport
            else:
                transport = TransportFactory.create_transport(
                    host=session.target_host,
                    port=session.target_port,
                    timeout_ms=session.timeout_per_test_ms,
                    transport_type=session.transport.value if session.transport else "tcp",
                )

            # Execute test case via transport
            try:
                if managed_transport:
                    response = await managed_transport.send_and_receive(
                        test_case.data,
                        timeout_ms=session.timeout_per_test_ms,
                    )
                    result = TestCaseResult.PASS
                else:
                    result, response = await transport.send_and_receive(test_case.data)

                # Apply protocol-specific validation if response received
                if result == TestCaseResult.PASS and response:
                    result = self.classify_response(session.protocol, response)

            except FuzzerConnectionRefusedError as exc:
                result, response = self._handle_connection_refused(
                    session, exc, on_connection_refused
                )

            except ConnectionTimeoutError as exc:
                logger.debug(
                    "target_timeout",
                    host=session.target_host,
                    port=session.target_port,
                    phase="connect",
                    error=str(exc),
                )
                result = TestCaseResult.HANG
                response = None

            except ReceiveTimeoutError as exc:
                logger.debug(
                    "target_timeout",
                    host=session.target_host,
                    port=session.target_port,
                    phase="receive",
                    error=str(exc),
                )
                result = TestCaseResult.HANG
                response = None

            except TransportError as exc:
                logger.error(
                    "transport_error",
                    error=str(exc),
                    test_case_id=test_case.id,
                    details=getattr(exc, "details", {}),
                )
                result = TestCaseResult.CRASH
                response = None

            finally:
                # Only cleanup ephemeral transports
                if not managed_transport:
                    await transport.cleanup()

        except Exception as e:
            logger.error("execution_error", error=str(e), test_case_id=test_case.id)
            result = TestCaseResult.CRASH
            response = None

            # If managed transport error, mark as unhealthy and trigger cleanup
            if managed_transport:
                managed_transport.healthy = False
                if self._connection_manager:
                    await self._connection_manager.cleanup_unhealthy(session.id)

        # Update test case with results
        test_case.result = result
        test_case.execution_time_ms = (time.time() - start_time) * 1000

        return result, response

    def classify_response(self, protocol: str, response: bytes) -> TestCaseResult:
        """
        Classify a response using the protocol's validator.

        Args:
            protocol: Protocol name
            response: Response bytes to classify

        Returns:
            TestCaseResult (PASS or LOGICAL_FAILURE)
        """
        if not self._validator_provider:
            return TestCaseResult.PASS

        validator = self._validator_provider(protocol)
        if not validator:
            return TestCaseResult.PASS

        try:
            is_valid = validator(response)
            return TestCaseResult.PASS if is_valid else TestCaseResult.LOGICAL_FAILURE
        except Exception as exc:
            logger.warning("validator_exception", error=str(exc))
            return TestCaseResult.LOGICAL_FAILURE

    def _should_use_persistent_connection(self, session: FuzzSession) -> bool:
        """Determine if session should use persistent connections."""
        return (
            session.connection_mode != "per_test"
            and session.protocol_stack_config is not None
        )

    def _handle_connection_refused(
        self,
        session: FuzzSession,
        exc: FuzzerConnectionRefusedError,
        callback: Optional[Callable[[FuzzSession, str], None]],
    ) -> Tuple[TestCaseResult, None]:
        """Handle connection refused error."""
        logger.error(
            "target_connection_refused",
            host=session.target_host,
            port=session.target_port,
            error=str(exc),
        )

        error_msg = (
            f"Connection refused to {session.target_host}:{session.target_port}. "
            "Target may not be running. If running in containers and targeting localhost, "
            "use '172.17.0.1' (Docker Linux), 'host.docker.internal' (Docker Mac/Windows), "
            "or 'host.containers.internal' (Podman 4.1+) instead."
        )

        if callback:
            callback(session, error_msg)

        return TestCaseResult.CRASH, None

    @staticmethod
    def build_connection_error_message(session: FuzzSession) -> str:
        """Build a user-friendly connection error message."""
        return (
            f"Connection refused to {session.target_host}:{session.target_port}. "
            "Target may not be running. If running in containers and targeting localhost, "
            "use '172.17.0.1' (Docker Linux), 'host.docker.internal' (Docker Mac/Windows), "
            "or 'host.containers.internal' (Podman 4.1+) instead."
        )
