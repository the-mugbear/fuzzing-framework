"""
Stage Runner - Executes protocol stages for orchestrated sessions.

Handles bootstrap, fuzz target, and teardown stage execution with:
- Response validation (expect)
- Context value extraction (exports)
- Retry logic for transient failures
- History recording for replay
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING, Union

import structlog

from core.engine.protocol_context import ProtocolContext
from core.engine.protocol_parser import ProtocolParser
from core.engine.transport import Transport, TransportFactory
from core.exceptions import TransportError
from core.models import (
    FuzzSession,
    ProtocolStageStatus,
    TestCaseExecutionRecord,
    TestCaseResult,
    TransportProtocol,
)
from core.plugin_loader import denormalize_data_model_from_json, PluginManager

if TYPE_CHECKING:
    from core.engine.connection_manager import ConnectionManager, ManagedTransport
    from core.engine.history_store import ExecutionHistoryStore

logger = structlog.get_logger()


class BootstrapError(Exception):
    """Raised when a bootstrap stage fails."""

    def __init__(self, stage_name: str, message: str, attempt: int = 0):
        self.stage_name = stage_name
        self.attempt = attempt
        super().__init__(f"Bootstrap stage '{stage_name}' failed: {message}")


class BootstrapValidationError(BootstrapError):
    """Raised when bootstrap response validation fails."""

    def __init__(self, stage_name: str, field: str, expected: Any, actual: Any):
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(
            stage_name,
            f"Validation failed: {field}={actual}, expected={expected}",
        )


class StageRunner:
    """
    Executes protocol stages within an orchestrated session.

    Handles the execution of:
    - Bootstrap stages: Run once per connection, extract context values
    - Fuzz target stages: Main fuzzing loop (delegated to orchestrator)
    - Teardown stages: Cleanup after fuzzing (if defined)

    Supports both per-test connections (ephemeral) and persistent connections
    via ConnectionManager. When connection_manager is provided and session uses
    persistent connection mode (session/per_stage), bootstrap stages use the
    same connection that will be used for fuzzing.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        context: ProtocolContext,
        history_store: Optional["ExecutionHistoryStore"] = None,
        connection_manager: Optional["ConnectionManager"] = None,
        use_replay_transport: bool = False,
    ):
        """
        Initialize the stage runner.

        Args:
            plugin_manager: Plugin manager for loading protocol definitions
            context: ProtocolContext for storing extracted values
            history_store: Optional history store for recording executions
            connection_manager: Optional ConnectionManager for persistent connections
            use_replay_transport: If True, use registered replay transport instead of
                                  session's normal transport (for replay isolation)
        """
        self.plugin_manager = plugin_manager
        self.context = context
        self.history_store = history_store
        self.connection_manager = connection_manager
        self.use_replay_transport = use_replay_transport
        self._stage_statuses: Dict[str, ProtocolStageStatus] = {}
        self._protocol_stages: Dict[str, Dict[str, Any]] = {}  # Stage definitions by name
        self._last_session: Optional[FuzzSession] = None  # For rerun support
        self._bootstrap_sequence: int = 0  # Sequence counter for bootstrap stages

    def get_stage_statuses(self) -> List[ProtocolStageStatus]:
        """Get status of all stages."""
        return list(self._stage_statuses.values())

    def get_stage_status(self, stage_name: str) -> Optional[ProtocolStageStatus]:
        """Get status of a specific stage."""
        return self._stage_statuses.get(stage_name)

    async def rerun_stage(self, stage_name: str) -> None:
        """
        Re-run a specific bootstrap stage.

        Useful for refreshing tokens or testing stage execution manually.
        Only works for bootstrap stages that have been previously run.

        Args:
            stage_name: Name of the stage to re-run

        Raises:
            ValueError: If stage not found or not a bootstrap stage
            BootstrapError: If stage execution fails
        """
        if stage_name not in self._protocol_stages:
            available = list(self._protocol_stages.keys())
            raise ValueError(
                f"Stage '{stage_name}' not found. Available stages: {available}"
            )

        stage = self._protocol_stages[stage_name]
        if stage.get("role") != "bootstrap":
            raise ValueError(
                f"Cannot rerun stage '{stage_name}': only bootstrap stages can be re-run"
            )

        if not self._last_session:
            raise ValueError("No session available for stage re-run")

        logger.info("rerunning_stage", stage_name=stage_name)

        # Reset status
        self._stage_statuses[stage_name] = ProtocolStageStatus(
            name=stage_name,
            role="bootstrap",
            status="active",
            started_at=datetime.utcnow(),
        )

        try:
            await self._run_bootstrap_stage(self._last_session, stage)
            self._stage_statuses[stage_name].status = "complete"
            self._stage_statuses[stage_name].completed_at = datetime.utcnow()
            logger.info("stage_rerun_complete", stage_name=stage_name)
        except BootstrapError:
            self._stage_statuses[stage_name].status = "failed"
            raise

    async def run_bootstrap_stages(
        self,
        session: FuzzSession,
        stages: List[Dict[str, Any]],
    ) -> bool:
        """
        Execute all bootstrap stages in order.

        Args:
            session: The fuzzing session
            stages: List of stage definitions from protocol_stack

        Returns:
            True if all bootstrap stages succeeded

        Raises:
            BootstrapError: If any bootstrap stage fails after retries
        """
        # Store session and stage definitions for rerun support
        self._last_session = session
        for stage in stages:
            name = stage.get("name", "unnamed")
            self._protocol_stages[name] = stage

        bootstrap_stages = [s for s in stages if s.get("role") == "bootstrap"]

        if not bootstrap_stages:
            logger.debug("no_bootstrap_stages", session_id=session.id)
            self.context.bootstrap_complete = True
            return True

        logger.info(
            "bootstrap_starting",
            session_id=session.id,
            stage_count=len(bootstrap_stages),
        )

        for stage in bootstrap_stages:
            stage_name = stage.get("name", "unnamed")

            # Initialize status tracking
            self._stage_statuses[stage_name] = ProtocolStageStatus(
                name=stage_name,
                role="bootstrap",
                status="active",
                started_at=datetime.utcnow(),
            )

            try:
                await self._run_bootstrap_stage(session, stage)
                self._stage_statuses[stage_name].status = "complete"
                self._stage_statuses[stage_name].completed_at = datetime.utcnow()

            except BootstrapError as e:
                self._stage_statuses[stage_name].status = "failed"
                self._stage_statuses[stage_name].error_message = str(e)
                raise

        self.context.bootstrap_complete = True
        logger.info(
            "bootstrap_complete",
            session_id=session.id,
            context_keys=self.context.keys(),
        )
        return True

    async def _run_bootstrap_stage(
        self,
        session: FuzzSession,
        stage: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a single bootstrap stage with retry logic.

        Args:
            session: The fuzzing session
            stage: Stage definition from protocol_stack

        Returns:
            Parsed response from the stage

        Raises:
            BootstrapError: If stage fails after all retry attempts
        """
        stage_name = stage.get("name", "unnamed")
        retry_config = stage.get("retry", {"max_attempts": 1, "backoff_ms": 0})
        max_attempts = retry_config.get("max_attempts", 1)
        backoff_ms = retry_config.get("backoff_ms", 0)

        last_error: Optional[Exception] = None

        for attempt in range(max_attempts):
            try:
                return await self._execute_bootstrap_attempt(session, stage, attempt)

            except BootstrapValidationError:
                # Validation errors are not retryable
                raise

            except Exception as e:
                last_error = e
                logger.warning(
                    "bootstrap_attempt_failed",
                    stage=stage_name,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    error=str(e),
                )

                if attempt < max_attempts - 1:
                    await asyncio.sleep(backoff_ms / 1000)

        # All attempts failed
        raise BootstrapError(
            stage_name,
            f"Failed after {max_attempts} attempts: {last_error}",
            attempt=max_attempts,
        )

    async def _execute_bootstrap_attempt(
        self,
        session: FuzzSession,
        stage: Dict[str, Any],
        attempt: int,
    ) -> Dict[str, Any]:
        """
        Execute a single bootstrap attempt.

        Uses ConnectionManager for persistent connections (session/per_stage mode)
        to ensure bootstrap and fuzzing share the same TCP connection. This is
        critical for protocols where auth tokens are tied to the connection.

        Args:
            session: The fuzzing session
            stage: Stage definition
            attempt: Current attempt number (0-indexed)

        Returns:
            Parsed response dictionary
        """
        stage_name = stage.get("name", "unnamed")

        # Build the request message
        data_model = denormalize_data_model_from_json(stage["data_model"])
        parser = ProtocolParser(data_model)
        message = parser.serialize(
            parser.build_default_fields(),
            context=self.context,
        )

        # Determine if we should use persistent connection
        use_persistent = (
            self.connection_manager is not None
            and session.connection_mode in ("session", "per_stage")
        )

        start_time = datetime.utcnow()

        if use_persistent:
            # Set current_stage for per_stage connection mode (used in _get_connection_id)
            session.current_stage = stage_name
            # Use ConnectionManager's persistent transport
            managed_transport = await self.connection_manager.get_transport(
                session, use_replay_transport=self.use_replay_transport
            )
            try:
                response = await managed_transport.send_and_receive(
                    message,
                    timeout_ms=session.timeout_per_test_ms,
                )
                result = TestCaseResult.PASS
            except Exception as e:
                managed_transport.healthy = False
                raise BootstrapError(
                    stage_name,
                    f"Transport error: {e}",
                    attempt=attempt,
                )
            # Don't close - persistent connection stays open
        else:
            # Use per-test ephemeral transport
            transport = self._create_transport(session)
            try:
                result, response = await transport.send_and_receive(message)
            finally:
                await transport.cleanup()

        end_time = datetime.utcnow()
        duration_ms = (end_time - start_time).total_seconds() * 1000

        # Handle connection/send failures
        if result != TestCaseResult.PASS:
            raise BootstrapError(
                stage_name,
                f"Transport error: {result.value}",
                attempt=attempt,
            )

        if response is None:
            raise BootstrapError(
                stage_name,
                "No response received",
                attempt=attempt,
            )

        # Parse response
        parsed = {}
        if stage.get("response_model"):
            response_model = denormalize_data_model_from_json(stage["response_model"])
            resp_parser = ProtocolParser(response_model)
            try:
                parsed = resp_parser.parse(response)
            except Exception as e:
                raise BootstrapError(
                    stage_name,
                    f"Failed to parse response: {e}",
                    attempt=attempt,
                )

        # Validate response if expect is specified
        if stage.get("expect"):
            self._validate_response(parsed, stage["expect"], stage_name)

        # Export values to context
        exports_captured = {}
        for resp_field, export_spec in stage.get("exports", {}).items():
            # Handle both simple string and dict with 'as' key
            if isinstance(export_spec, dict):
                context_key = export_spec.get("as", resp_field)
                transforms = export_spec.get("transform", [])
            else:
                context_key = export_spec
                transforms = []

            value = self._extract_value(parsed, resp_field)
            if value is not None:
                # Apply transforms if specified
                if transforms:
                    value = self._apply_export_transforms(value, transforms)

                self.context.set(context_key, value)
                exports_captured[context_key] = True
                logger.debug(
                    "context_value_exported",
                    stage=stage_name,
                    field=resp_field,
                    context_key=context_key,
                    value_type=type(value).__name__,
                )
            else:
                exports_captured[context_key] = False
                logger.warning(
                    "export_value_not_found",
                    stage=stage_name,
                    field=resp_field,
                    context_key=context_key,
                )

        # Update stage status with exports
        if stage_name in self._stage_statuses:
            self._stage_statuses[stage_name].exports_captured = exports_captured

        # Record execution in history
        if self.history_store:
            await self._record_bootstrap_execution(
                session=session,
                stage_name=stage_name,
                message=message,
                response=response,
                parsed_response=parsed,
                duration_ms=duration_ms,
                result=TestCaseResult.PASS,
            )

        return parsed

    def _validate_response(
        self,
        parsed: Dict[str, Any],
        expect: Dict[str, Any],
        stage_name: str,
    ) -> None:
        """
        Validate parsed response against expected values.

        Args:
            parsed: Parsed response dictionary
            expect: Expected field values
            stage_name: Name of the stage (for error messages)

        Raises:
            BootstrapValidationError: If validation fails
        """
        for field, expected in expect.items():
            actual = parsed.get(field)

            # Handle list of acceptable values
            if isinstance(expected, list):
                if actual not in expected:
                    raise BootstrapValidationError(
                        stage_name, field, expected, actual
                    )
            else:
                if actual != expected:
                    raise BootstrapValidationError(
                        stage_name, field, expected, actual
                    )

    def _extract_value(self, parsed: Dict[str, Any], field_spec: str) -> Any:
        """
        Extract a value from parsed response, supporting dotted paths.

        Args:
            parsed: Parsed response dictionary
            field_spec: Field name or dotted path (e.g., "header.token")

        Returns:
            Extracted value or None if not found
        """
        parts = field_spec.split(".")
        value = parsed

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value

    def _apply_export_transforms(
        self,
        value: Any,
        transforms: List[Dict[str, Any]],
    ) -> Any:
        """
        Apply transforms to an exported value.

        Uses the same transform operations as ProtocolParser.

        Args:
            value: Value to transform
            transforms: List of transform operations

        Returns:
            Transformed value
        """
        if not isinstance(value, int):
            return value

        for transform in transforms:
            if not isinstance(transform, dict):
                continue

            operation = transform.get("operation")
            op_value = transform.get("value")
            bit_width = transform.get("bit_width")

            # Parse op_value if string
            if isinstance(op_value, str):
                try:
                    op_value = int(op_value, 0)
                except ValueError:
                    op_value = None

            if operation == "add_constant" and op_value is not None:
                value = value + op_value
            elif operation == "subtract_constant" and op_value is not None:
                value = value - op_value
            elif operation == "xor_constant" and op_value is not None:
                value = value ^ op_value
            elif operation == "and_mask" and op_value is not None:
                value = value & op_value
            elif operation == "or_mask" and op_value is not None:
                value = value | op_value
            elif operation == "shift_left" and op_value is not None:
                value = value << op_value
            elif operation == "shift_right" and op_value is not None:
                value = value >> op_value
            elif operation == "modulo" and op_value is not None and op_value != 0:
                value = value % op_value
            elif operation == "invert":
                if bit_width is not None and bit_width > 0:
                    mask = (1 << bit_width) - 1
                    value = (~value) & mask
                elif op_value is not None:
                    value = (~value) & op_value

        return value

    def _create_transport(self, session: FuzzSession) -> Transport:
        """Create transport for the session."""
        # Determine transport type from session
        transport_type = getattr(session, "transport", TransportProtocol.TCP)

        if transport_type == TransportProtocol.UDP:
            return TransportFactory.create_udp_transport(
                session.target_host,
                session.target_port,
                session.timeout_per_test_ms,
            )
        else:
            return TransportFactory.create_tcp_transport(
                session.target_host,
                session.target_port,
                session.timeout_per_test_ms,
            )

    async def _record_bootstrap_execution(
        self,
        session: FuzzSession,
        stage_name: str,
        message: bytes,
        response: bytes,
        parsed_response: Dict[str, Any],
        duration_ms: float,
        result: TestCaseResult,
    ) -> None:
        """Record bootstrap execution in history store."""
        if not self.history_store:
            return

        # Generate unique test case ID
        test_case_id = str(uuid.uuid4())

        # Calculate payload hash
        payload_hash = hashlib.sha256(message).hexdigest()

        # Use negative sequence numbers for bootstrap stages (-1, -2, -3, ...)
        # This avoids collision with fuzz executions (which start at 1)
        # and allows multiple bootstrap stages to be stored
        self._bootstrap_sequence -= 1
        bootstrap_seq = self._bootstrap_sequence

        record = TestCaseExecutionRecord(
            test_case_id=test_case_id,
            session_id=session.id,
            sequence_number=bootstrap_seq,
            timestamp_sent=datetime.utcnow(),
            timestamp_response=datetime.utcnow(),
            duration_ms=duration_ms,
            payload_size=len(message),
            payload_hash=payload_hash,
            payload_preview=message[:64].hex(),
            protocol=session.protocol,
            message_type=None,
            state_at_send=None,
            result=result,
            response_size=len(response) if response else 0,
            response_preview=response[:64].hex() if response else None,
            error_message=None,
            raw_response_b64=base64.b64encode(response).decode() if response else None,
            raw_payload_b64=base64.b64encode(message).decode(),
            mutation_strategy=None,
            mutators_applied=[],
            # Orchestration fields
            stage_name=stage_name,
            context_snapshot=self.context.snapshot(),
            connection_sequence=0,
            parsed_fields=parsed_response,
        )

        self.history_store.record_direct(record)
        logger.debug(
            "bootstrap_execution_recorded",
            session_id=session.id,
            stage=stage_name,
            test_case_id=test_case_id,
        )

    async def run_teardown_stages(
        self,
        session: FuzzSession,
        stages: List[Dict[str, Any]],
    ) -> bool:
        """
        Execute all teardown stages in order.

        Args:
            session: The fuzzing session
            stages: List of stage definitions from protocol_stack

        Returns:
            True if all teardown stages succeeded (failures are logged but don't raise)
        """
        teardown_stages = [s for s in stages if s.get("role") == "teardown"]

        if not teardown_stages:
            logger.debug("no_teardown_stages", session_id=session.id)
            return True

        logger.info(
            "teardown_starting",
            session_id=session.id,
            stage_count=len(teardown_stages),
        )

        all_succeeded = True

        for stage in teardown_stages:
            stage_name = stage.get("name", "unnamed")

            self._stage_statuses[stage_name] = ProtocolStageStatus(
                name=stage_name,
                role="teardown",
                status="active",
                started_at=datetime.utcnow(),
            )

            try:
                await self._run_teardown_stage(session, stage)
                self._stage_statuses[stage_name].status = "complete"
                self._stage_statuses[stage_name].completed_at = datetime.utcnow()

            except Exception as e:
                # Teardown failures are logged but don't fail the session
                self._stage_statuses[stage_name].status = "failed"
                self._stage_statuses[stage_name].error_message = str(e)
                all_succeeded = False
                logger.warning(
                    "teardown_stage_failed",
                    session_id=session.id,
                    stage=stage_name,
                    error=str(e),
                )

        return all_succeeded

    async def _run_teardown_stage(
        self,
        session: FuzzSession,
        stage: Dict[str, Any],
    ) -> None:
        """
        Execute a single teardown stage.

        Teardown stages are simpler than bootstrap - no retry, no exports.
        Uses ConnectionManager for persistent modes to send on existing connection.
        """
        stage_name = stage.get("name", "unnamed")

        # Build the request message
        data_model = denormalize_data_model_from_json(stage["data_model"])
        parser = ProtocolParser(data_model)
        message = parser.serialize(
            parser.build_default_fields(),
            context=self.context,
        )

        # Determine if we should use persistent connection
        use_persistent = (
            self.connection_manager is not None
            and session.connection_mode in ("session", "per_stage")
        )

        if use_persistent:
            # Set current_stage for per_stage connection mode
            session.current_stage = stage_name
            # Use existing connection for teardown
            managed_transport = await self.connection_manager.get_transport(
                session, use_replay_transport=self.use_replay_transport
            )
            try:
                await managed_transport.send_and_receive(
                    message,
                    timeout_ms=session.timeout_per_test_ms,
                )
            except Exception as e:
                # Teardown failures are logged but don't propagate transport errors
                logger.warning(
                    "teardown_transport_error",
                    session_id=session.id,
                    stage=stage_name,
                    error=str(e),
                )
            # Don't close - connection cleanup happens in ConnectionManager.close_session()
        else:
            # Use per-test ephemeral transport
            transport = self._create_transport(session)
            try:
                await transport.send_and_receive(message)
            finally:
                await transport.cleanup()

        logger.debug(
            "teardown_stage_complete",
            session_id=session.id,
            stage=stage_name,
        )

    def get_fuzz_target_stage(
        self,
        stages: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Get the fuzz target stage from the protocol stack.

        Args:
            stages: List of stage definitions

        Returns:
            The first fuzz_target stage, or None if not found
        """
        for stage in stages:
            if stage.get("role") == "fuzz_target":
                return stage
        return None

    def reset_for_reconnect(self, clear_context: bool = True) -> None:
        """
        Reset stage runner state for reconnection.

        Args:
            clear_context: If True, clear all context values
        """
        if clear_context:
            self.context.clear()

        # Reset stage statuses to pending
        for status in self._stage_statuses.values():
            if status.role == "bootstrap":
                status.status = "pending"
                status.started_at = None
                status.completed_at = None
                status.error_message = None
                status.exports_captured = {}

        logger.debug("stage_runner_reset_for_reconnect", clear_context=clear_context)
