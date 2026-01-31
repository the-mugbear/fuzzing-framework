"""
Replay Executor - Replays executions with context reconstruction.

Enables reliable reproduction of issues by rebuilding session state
through replay. Supports multiple modes for different use cases.

Replay modes:
- fresh: Re-run bootstrap, re-serialize with new context
- stored: Replay exact historical bytes (token is long-lived)
- skip: No bootstrap, assume target ready (manual testing)
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import structlog

from core.engine.history_store import ExecutionHistoryStore
from core.engine.protocol_context import ProtocolContext
from core.engine.protocol_parser import ProtocolParser
from core.exceptions import ReceiveTimeoutError
from core.plugin_loader import denormalize_data_model_from_json

if TYPE_CHECKING:
    from core.engine.connection_manager import ConnectionManager, ManagedTransport
    from core.engine.stage_runner import StageRunner
    from core.models import FuzzSession, TestCaseExecutionRecord
    from core.plugin_loader import PluginManager

logger = structlog.get_logger()


class ReplayMode(str, Enum):
    """Mode for replay execution."""
    FRESH = "fresh"    # Re-run bootstrap, re-serialize with new context
    STORED = "stored"  # Replay exact historical bytes
    SKIP = "skip"      # No bootstrap, assume target ready


@dataclass
class ReplayResult:
    """Result of replaying a single execution."""
    original_sequence: int
    status: str  # "success", "timeout", "error"
    response_preview: Optional[str] = None  # First 100 bytes as hex
    error: Optional[str] = None
    duration_ms: float = 0.0
    matched_original: bool = False  # Response matches original


@dataclass
class ReplayResponse:
    """Response from a replay operation."""
    replayed_count: int
    skipped_count: int = 0  # Bootstrap stages skipped
    results: List[ReplayResult] = field(default_factory=list)
    context_after: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    duration_ms: float = 0.0


class ReplayError(Exception):
    """Raised when replay fails."""
    pass


class ReplayExecutor:
    """
    Executes replay with context reconstruction.

    Supports three modes:
    - fresh: Re-run bootstrap stages to get new tokens, re-serialize
             messages with current context. Use when tokens are per-connection.
    - stored: Replay exact historical bytes. Use when tokens are long-lived
              or deterministic.
    - skip: No bootstrap, empty context. Use for manual testing when
            target is pre-configured.

    Example usage:
        executor = ReplayExecutor(
            plugin_manager,
            connection_manager,
            history_store,
            stage_runner,
        )

        results = await executor.replay_up_to(
            session,
            target_sequence=150,
            mode=ReplayMode.FRESH,
            delay_ms=100,
        )
    """

    def __init__(
        self,
        plugin_manager: "PluginManager",
        connection_manager: "ConnectionManager",
        history_store: ExecutionHistoryStore,
        stage_runner: Optional["StageRunner"] = None,
    ):
        """
        Initialize the ReplayExecutor.

        Args:
            plugin_manager: For loading protocol plugins
            connection_manager: For creating replay connections
            history_store: For retrieving execution history
            stage_runner: For running bootstrap stages (optional, created if needed)
        """
        self._plugin_manager = plugin_manager
        self._connection_manager = connection_manager
        self._history_store = history_store
        self._stage_runner = stage_runner

    async def replay_up_to(
        self,
        session: "FuzzSession",
        target_sequence: int,
        mode: ReplayMode = ReplayMode.FRESH,
        delay_ms: int = 0,
        stop_on_error: bool = False,
    ) -> ReplayResponse:
        """
        Replay all executions from start up to target sequence.

        Args:
            session: The fuzzing session
            target_sequence: Replay executions 1 through this number
            mode: How to handle bootstrap/context
            delay_ms: Delay between replayed messages
            stop_on_error: Stop replay on first error

        Returns:
            ReplayResponse with results and final context

        Raises:
            ReplayError: If replay fails fatally
        """
        start_time = datetime.utcnow()
        warnings: List[str] = []

        # Get execution history in ascending order
        executions = self._history_store.list_for_replay(
            session.id,
            up_to_sequence=target_sequence,
        )

        if not executions:
            raise ReplayError("No executions found in history")

        # Validate history completeness
        first_seq = executions[0].sequence_number
        if first_seq != 1:
            warnings.append(
                f"History does not start at sequence 1 (starts at {first_seq}). "
                f"Replay may fail if early messages are required."
            )

        last_seq = executions[-1].sequence_number
        if last_seq < target_sequence:
            warnings.append(
                f"Requested replay up to {target_sequence} but history only "
                f"contains up to {last_seq}. Replaying available range."
            )

        # Get protocol configuration
        plugin = self._plugin_manager.load_plugin(session.protocol)
        if not plugin:
            raise ReplayError(f"Plugin not found: {session.protocol}")

        protocol_stack = self._plugin_manager.get_protocol_stack(session.protocol)
        fuzz_stage = self._get_fuzz_target_stage(protocol_stack) if protocol_stack else None

        # Setup connection and context based on mode
        context = ProtocolContext()
        transport: Optional["ManagedTransport"] = None

        try:
            if mode == ReplayMode.FRESH:
                # For FRESH mode, bootstrap and replay must share the same connection
                # for connection-bound tokens (auth tied to TCP session) to work.
                # Create the replay transport and register it so StageRunner uses it.
                transport = await self._connection_manager.create_replay_transport(session)

                # Register the replay transport so get_transport() returns it
                self._connection_manager.register_replay_transport(session.id, transport)

                if protocol_stack:
                    bootstrap_stages = [
                        s for s in protocol_stack if s.get("role") == "bootstrap"
                    ]
                    if bootstrap_stages:
                        # Create stage runner with connection_manager for persistent connection
                        stage_runner = self._stage_runner
                        if not stage_runner:
                            from core.engine.stage_runner import StageRunner
                            stage_runner = StageRunner(
                                plugin_manager=self._plugin_manager,
                                context=context,
                                history_store=self._history_store,
                                connection_manager=self._connection_manager,
                                use_replay_transport=True,  # Use registered replay transport
                            )
                            logger.debug(
                                "replay_created_stage_runner",
                                session_id=session.id,
                                bootstrap_count=len(bootstrap_stages),
                            )

                        # Temporarily set connection_mode to 'session' for bootstrap
                        # so StageRunner uses ConnectionManager (gets registered replay transport)
                        original_mode = session.connection_mode
                        session.connection_mode = "session"
                        try:
                            await stage_runner.run_bootstrap_stages(
                                session, bootstrap_stages
                            )
                        finally:
                            session.connection_mode = original_mode
                        # Get context from stage runner (may have been updated)
                        context = stage_runner.context

            elif mode == ReplayMode.STORED:
                # Create isolated transport for replay (not cached)
                transport = await self._connection_manager.create_replay_transport(session)

                if executions[0].context_snapshot:
                    context.restore(executions[0].context_snapshot)
                else:
                    warnings.append(
                        "First execution has no context snapshot. "
                        "Replay may fail if protocol requires context values."
                    )

            else:  # SKIP
                # Create isolated transport for replay (not cached)
                transport = await self._connection_manager.create_replay_transport(session)

            # Get parser for re-serialization if using FRESH mode
            parser: Optional[ProtocolParser] = None
            if mode == ReplayMode.FRESH and fuzz_stage:
                data_model = fuzz_stage.get("data_model", {})
                if data_model:
                    # Denormalize data_model (converts base64 back to bytes)
                    denormalized = denormalize_data_model_from_json(data_model)
                    parser = ProtocolParser(denormalized)

            # Replay executions
            results: List[ReplayResult] = []
            skipped_count = 0

            for execution in executions:
                # Determine if this execution should be replayed
                # - Replay if no stage_name (legacy data or non-orchestrated)
                # - Replay if stage_name matches the fuzz_target stage
                # - Skip bootstrap/teardown stages
                if execution.stage_name:
                    fuzz_stage_name = fuzz_stage.get("name") if fuzz_stage else None
                    if fuzz_stage_name and execution.stage_name != fuzz_stage_name:
                        # This is a bootstrap or teardown execution, skip it
                        skipped_count += 1
                        logger.debug(
                            "replay_skipping_non_fuzz_stage",
                            stage_name=execution.stage_name,
                            fuzz_stage=fuzz_stage_name,
                            sequence=execution.sequence_number,
                        )
                        continue

                result = await self._replay_single(
                    transport=transport,
                    execution=execution,
                    context=context,
                    parser=parser,
                    mode=mode,
                    timeout_ms=session.timeout_per_test_ms,
                )
                results.append(result)

                if stop_on_error and result.status == "error":
                    break

                # Delay between messages
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000)

            # Calculate total duration
            end_time = datetime.utcnow()
            duration_ms = (end_time - start_time).total_seconds() * 1000

            return ReplayResponse(
                replayed_count=len(results),
                skipped_count=skipped_count,
                results=results,
                context_after=context.snapshot(),
                warnings=warnings,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.error(
                "replay_failed",
                session_id=session.id,
                target_sequence=target_sequence,
                error=str(e),
            )
            raise ReplayError(f"Replay failed: {e}")

        finally:
            # Unregister replay transport if we registered it (FRESH mode)
            if mode == ReplayMode.FRESH:
                self._connection_manager.unregister_replay_transport(session.id)
            if transport:
                await transport.close()

    async def replay_single(
        self,
        session: "FuzzSession",
        sequence_number: int,
        mode: ReplayMode = ReplayMode.STORED,
    ) -> ReplayResult:
        """
        Replay a single execution by sequence number.

        This is a convenience method for replaying just one message.
        Note: For stateful protocols, this may fail if the target
        is not in the expected state.

        Args:
            session: The fuzzing session
            sequence_number: Sequence number to replay
            mode: Replay mode (STORED is default for single replay)

        Returns:
            ReplayResult for the execution
        """
        execution = self._history_store.find_by_sequence(
            session.id, sequence_number
        )
        if not execution:
            return ReplayResult(
                original_sequence=sequence_number,
                status="error",
                error=f"Execution {sequence_number} not found in history",
            )

        # Use isolated replay transport to avoid affecting active session's connection
        transport = await self._connection_manager.create_replay_transport(session)
        context = ProtocolContext()

        if execution.context_snapshot:
            context.restore(execution.context_snapshot)

        try:
            return await self._replay_single(
                transport=transport,
                execution=execution,
                context=context,
                parser=None,
                mode=mode,
                timeout_ms=session.timeout_per_test_ms,
            )
        finally:
            await transport.close()

    async def _replay_single(
        self,
        transport: "ManagedTransport",
        execution: "TestCaseExecutionRecord",
        context: ProtocolContext,
        parser: Optional[ProtocolParser],
        mode: ReplayMode,
        timeout_ms: int,
    ) -> ReplayResult:
        """
        Replay a single execution.

        Args:
            transport: Connection to use
            execution: Execution record to replay
            context: Current protocol context
            parser: Parser for re-serialization (FRESH mode)
            mode: Replay mode
            timeout_ms: Response timeout

        Returns:
            ReplayResult for the execution
        """
        start_time = datetime.utcnow()

        try:
            # Determine payload
            if mode == ReplayMode.STORED:
                # Use exact historical bytes
                payload = base64.b64decode(execution.raw_payload_b64)

            elif mode == ReplayMode.FRESH:
                # Re-serialize with current context
                if execution.parsed_fields and parser:
                    payload = parser.serialize(
                        execution.parsed_fields,
                        context=context,
                    )
                else:
                    # Fallback: use historical bytes
                    payload = base64.b64decode(execution.raw_payload_b64)
                    logger.debug(
                        "replay_missing_parsed_fields",
                        sequence=execution.sequence_number,
                    )

            else:  # SKIP
                payload = base64.b64decode(execution.raw_payload_b64)

            # Send and receive
            await transport.send(payload)
            response = await transport.recv(timeout_ms=timeout_ms)

            end_time = datetime.utcnow()
            duration_ms = (end_time - start_time).total_seconds() * 1000

            # Check if response matches original
            matched = False
            if execution.raw_response_b64:
                original_response = base64.b64decode(execution.raw_response_b64)
                matched = response == original_response

            return ReplayResult(
                original_sequence=execution.sequence_number,
                status="success",
                response_preview=response[:100].hex() if response else None,
                duration_ms=duration_ms,
                matched_original=matched,
            )

        except ReceiveTimeoutError:
            end_time = datetime.utcnow()
            duration_ms = (end_time - start_time).total_seconds() * 1000
            return ReplayResult(
                original_sequence=execution.sequence_number,
                status="timeout",
                error="Response timeout",
                duration_ms=duration_ms,
            )

        except Exception as e:
            end_time = datetime.utcnow()
            duration_ms = (end_time - start_time).total_seconds() * 1000
            return ReplayResult(
                original_sequence=execution.sequence_number,
                status="error",
                error=str(e),
                duration_ms=duration_ms,
            )

    def _get_fuzz_target_stage(
        self,
        protocol_stack: Optional[List[Dict]],
    ) -> Optional[Dict]:
        """Get the fuzz_target stage from protocol stack."""
        if not protocol_stack:
            return None

        for stage in protocol_stack:
            if stage.get("role") == "fuzz_target":
                return stage

        return None
