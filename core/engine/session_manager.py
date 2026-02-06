"""
Session Manager - Manages fuzzing session lifecycle.

This module provides complete session lifecycle management, from creation
through execution to cleanup and deletion.

Component Overview:
-------------------
The SessionManager handles all session CRUD operations and lifecycle events:
- Session creation with protocol initialization
- Session start with bootstrap stages for orchestrated protocols
- Session stop with teardown stages
- Session deletion with full resource cleanup
- Session persistence and recovery on restart

Key Responsibilities:
--------------------
1. Session Creation:
   - Load and validate protocol plugin
   - Initialize corpus with protocol seeds
   - Create runtime context with behavior processors
   - Setup orchestration context if protocol has protocol_stack
   - Configure response planning if protocol has response_handlers

2. Session Start:
   - Enforce concurrent session limits
   - Check agent availability for AGENT mode
   - Execute bootstrap stages for orchestrated protocols
   - Start heartbeat scheduler if configured
   - Launch fuzzing task via callback

3. Session Stop:
   - Stop heartbeat scheduler
   - Execute teardown stages
   - Mark session as completed
   - Clean up resources (connections, contexts)
   - Flush pending execution history

4. Session Deletion:
   - Stop session if running
   - Clean up all resources
   - Remove from persistence store
   - Remove from in-memory tracking

5. Recovery:
   - Load sessions from disk on startup
   - Mark interrupted sessions as PAUSED
   - Rebuild runtime helpers for active sessions
   - Handle recovery failures gracefully

Integration Points:
------------------
- Uses CorpusStore for seed management
- Uses SessionStore for persistence
- Uses SessionContextManager for runtime state
- Uses ConnectionManager for persistent connections
- Integrates with orchestrator via callbacks

Usage Example:
-------------
    # Create manager
    manager = SessionManager(
        corpus_store=corpus_store,
        session_store=session_store,
    )

    # Set callbacks for orchestrator integration
    manager.set_callbacks(
        on_session_start=start_fuzzing_task,
        run_bootstrap=run_bootstrap_stages,
        run_teardown=run_teardown_stages,
    )

    # Create and start session
    session = await manager.create_session(config)
    await manager.start_session(session.id)

    # Later, stop and clean up
    await manager.stop_session(session.id)
    await manager.delete_session(session.id)

Configuration:
-------------
- max_concurrent_sessions: Limit from settings
- checkpoint_frequency: How often to save state

Note:
----
This module is part of the Phase 5 orchestrator decomposition. It extracts
session lifecycle management into a focused, testable component.

See Also:
--------
- core/engine/session_store.py - Session persistence
- core/engine/session_context.py - Runtime context management
- core/engine/orchestrator.py - Integrates SessionManager
- docs/developer/01_architectural_overview.md - Architecture documentation
"""
from __future__ import annotations

import asyncio
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

import structlog

from core.agents.manager import agent_manager
from core.config import settings
from core.corpus.store import CorpusStore
from core.engine.session_context import SessionContextManager, SessionRuntimeContext
from core.models import (
    ExecutionMode,
    FuzzConfig,
    FuzzSession,
    FuzzSessionStatus,
)
from core.plugin_loader import (
    decode_seeds_from_json,
    denormalize_data_model_from_json,
    plugin_manager,
)
from core.protocol_behavior import build_behavior_processor

if TYPE_CHECKING:
    from core.engine.connection_manager import ConnectionManager
    from core.engine.history_store import ExecutionHistoryStore
    from core.engine.response_planner import ResponsePlanner
    from core.engine.session_store import SessionStore

logger = structlog.get_logger()


class SessionManager:
    """
    Manages fuzzing session lifecycle.

    Handles:
    - Session creation with protocol initialization
    - Session start with bootstrap stages
    - Session stop with teardown stages
    - Session deletion and cleanup
    - Session persistence and recovery

    This component is designed to work with the orchestrator but can also
    be used standalone for testing.
    """

    def __init__(
        self,
        corpus_store: Optional[CorpusStore] = None,
        session_store: Optional["SessionStore"] = None,
        history_store: Optional["ExecutionHistoryStore"] = None,
        context_manager: Optional[SessionContextManager] = None,
    ):
        """
        Initialize the SessionManager.

        Args:
            corpus_store: CorpusStore for seed management
            session_store: SessionStore for persistence
            history_store: ExecutionHistoryStore for execution history
            context_manager: SessionContextManager for runtime state
        """
        self.corpus_store = corpus_store or CorpusStore()
        self.context_manager = context_manager or SessionContextManager()

        # Lazy import to avoid circular dependencies
        if session_store is None:
            from core.engine.session_store import SessionStore
            session_store = SessionStore()
        self.session_store = session_store

        if history_store is None:
            from core.engine.history_store import ExecutionHistoryStore
            history_store = ExecutionHistoryStore()
        self.history_store = history_store

        # Session storage
        self.sessions: Dict[str, FuzzSession] = {}
        self.active_tasks: Dict[str, asyncio.Task] = {}

        # Connection management (shared across sessions)
        self._connection_manager: Optional["ConnectionManager"] = None
        self._heartbeat_scheduler: Optional[Any] = None

        # Callbacks for orchestrator integration
        self._on_session_start: Optional[Callable[[FuzzSession], asyncio.Task]] = None
        self._run_bootstrap: Optional[Callable] = None
        self._run_teardown: Optional[Callable] = None
        self._start_heartbeat: Optional[Callable] = None

    def set_connection_manager(self, manager: "ConnectionManager") -> None:
        """Set the connection manager."""
        self._connection_manager = manager

    def set_heartbeat_scheduler(self, scheduler: Any) -> None:
        """Set the heartbeat scheduler."""
        self._heartbeat_scheduler = scheduler

    def set_callbacks(
        self,
        on_session_start: Optional[Callable[[FuzzSession], asyncio.Task]] = None,
        run_bootstrap: Optional[Callable] = None,
        run_teardown: Optional[Callable] = None,
        start_heartbeat: Optional[Callable] = None,
    ) -> None:
        """Set callbacks for orchestrator integration."""
        self._on_session_start = on_session_start
        self._run_bootstrap = run_bootstrap
        self._run_teardown = run_teardown
        self._start_heartbeat = start_heartbeat

    async def create_session(self, config: FuzzConfig) -> FuzzSession:
        """
        Create a new fuzzing session.

        Args:
            config: Fuzzing configuration

        Returns:
            FuzzSession object
        """
        session_id = str(uuid.uuid4())

        # Load protocol plugin
        try:
            protocol = plugin_manager.load_plugin(config.protocol)
            logger.info("protocol_loaded", protocol=config.protocol)
        except Exception as e:
            logger.error("failed_to_load_protocol", protocol=config.protocol, error=str(e))
            raise

        resolved_data_model = denormalize_data_model_from_json(protocol.data_model)
        resolved_response_model = (
            denormalize_data_model_from_json(protocol.response_model)
            if protocol.response_model
            else None
        )

        # Create runtime context for session
        ctx = self.context_manager.create_context(session_id)
        ctx.data_model = resolved_data_model
        ctx.response_model = resolved_response_model

        session_transport = config.transport or protocol.transport

        # Initialize seed corpus from plugin
        seed_corpus = []
        if "seeds" in protocol.data_model:
            seeds_bytes = decode_seeds_from_json(protocol.data_model["seeds"])
            for seed in seeds_bytes:
                seed_id = self.corpus_store.add_seed(
                    seed, metadata={"protocol": config.protocol, "source": "plugin"}
                )
                seed_corpus.append(seed_id)

        enabled_mutators = self._resolve_mutators(config)
        behavior_processor = build_behavior_processor(resolved_data_model)

        # Store behavior processor in context
        if behavior_processor.has_behaviors():
            ctx.behavior_processor = behavior_processor

        # Extract orchestration configuration from plugin
        protocol_stack = plugin_manager.get_protocol_stack(config.protocol)
        connection_config = protocol.get("connection", {}) if hasattr(protocol, "get") else {}
        heartbeat_config = protocol.get("heartbeat", {}) if hasattr(protocol, "get") else {}

        # Determine connection mode (from config or plugin)
        connection_mode = "per_test"
        if protocol_stack:
            connection_mode = connection_config.get("mode", "session")

        session = FuzzSession(
            id=session_id,
            protocol=config.protocol,
            target_host=config.target_host,
            target_port=config.target_port,
            transport=session_transport,
            seed_corpus=seed_corpus,
            enabled_mutators=enabled_mutators,
            timeout_per_test_ms=config.timeout_per_test_ms,
            rate_limit_per_second=config.rate_limit_per_second,
            mutation_mode=config.mutation_mode,
            structure_aware_weight=config.structure_aware_weight,
            max_iterations=config.max_iterations,
            execution_mode=config.execution_mode,
            status=FuzzSessionStatus.IDLE,
            behavior_state=behavior_processor.initialize_state() if behavior_processor.has_behaviors() else {},
            target_state=config.target_state,
            fuzzing_mode=config.fuzzing_mode,
            mutable_fields=config.mutable_fields,
            field_mutation_config=config.field_mutation_config,
            session_reset_interval=config.session_reset_interval,
            enable_termination_fuzzing=config.enable_termination_fuzzing,
            protocol_stack_config=protocol_stack,
            connection_mode=connection_mode,
            heartbeat_enabled=heartbeat_config.get("enabled", False) if heartbeat_config else False,
        )

        self.sessions[session_id] = session

        # Initialize ProtocolContext for orchestrated sessions
        if protocol_stack:
            from core.engine.protocol_context import ProtocolContext
            ctx.protocol_context = ProtocolContext()
            logger.debug(
                "orchestration_context_created",
                session_id=session_id,
                protocol_stack_stages=len(protocol_stack),
                connection_mode=connection_mode,
            )

        # Setup response planner if protocol has response handlers
        if protocol.response_handlers:
            from core.engine.response_planner import ResponsePlanner
            planner = ResponsePlanner(
                resolved_data_model,
                resolved_response_model,
                protocol.response_handlers,
            )
            ctx.response_planner = planner
            ctx.followup_queue = deque()

        # Save initial session state to disk
        await self._checkpoint_session(session)

        logger.info("session_created", session_id=session_id, protocol=config.protocol)
        return session

    async def start_session(self, session_id: str) -> bool:
        """
        Start a fuzzing session.

        Args:
            session_id: Session ID to start

        Returns:
            True if started successfully
        """
        session = self.sessions.get(session_id)
        if not session:
            logger.error("session_not_found", session_id=session_id)
            return False

        # Check concurrent session limit
        running_sessions = [
            s for s in self.sessions.values()
            if s.status == FuzzSessionStatus.RUNNING and s.id != session_id
        ]

        if len(running_sessions) >= settings.max_concurrent_sessions:
            running_session_ids = ", ".join([s.id[:8] for s in running_sessions[:3]])
            if len(running_sessions) > 3:
                running_session_ids += f" (+{len(running_sessions) - 3} more)"

            error_msg = (
                f"Cannot start session: maximum concurrent sessions limit reached "
                f"({len(running_sessions)}/{settings.max_concurrent_sessions}). "
                f"Currently running: {running_session_ids}. "
                f"Stop a session first, or increase FUZZER_MAX_CONCURRENT_SESSIONS."
            )
            session.error_message = error_msg
            logger.warning(
                "concurrent_session_limit_reached",
                session_id=session_id,
                running_count=len(running_sessions),
                limit=settings.max_concurrent_sessions,
            )
            return False

        if session.status == FuzzSessionStatus.RUNNING:
            logger.warning("session_already_running", session_id=session_id)
            return False

        # Check for agent availability in AGENT mode
        if session.execution_mode == ExecutionMode.AGENT:
            if not agent_manager.has_agent_for_target(
                session.target_host,
                session.target_port,
                session.transport,
            ):
                session.error_message = (
                    f"No live agents registered for target "
                    f"{session.target_host}:{session.target_port}"
                )
                session.status = FuzzSessionStatus.FAILED
                await self._checkpoint_session(session)
                logger.error("no_agents_for_session", session_id=session_id)
                return False

        # Apply connection configuration
        if session.connection_mode in ("session", "per_stage"):
            if self._connection_manager is None:
                from core.engine.connection_manager import ConnectionManager
                self._connection_manager = ConnectionManager()

            protocol = plugin_manager.load_plugin(session.protocol)
            connection_config = protocol.get("connection", {}) if hasattr(protocol, "get") else {}
            if connection_config:
                self._connection_manager.set_connection_config(session.id, connection_config)

        # Run bootstrap stages for orchestrated protocols
        if session.protocol_stack_config and self._run_bootstrap:
            bootstrap_stages = [
                s for s in session.protocol_stack_config
                if s.get("role") == "bootstrap"
            ]
            if bootstrap_stages:
                try:
                    await self._run_bootstrap(session, bootstrap_stages)
                    logger.info(
                        "bootstrap_complete",
                        session_id=session_id,
                        stages_run=len(bootstrap_stages),
                    )
                except Exception as e:
                    session.error_message = f"Bootstrap failed: {e}"
                    session.status = FuzzSessionStatus.FAILED
                    await self._checkpoint_session(session)
                    logger.error("bootstrap_failed", session_id=session_id, error=str(e))
                    return False

        session.status = FuzzSessionStatus.RUNNING
        session.started_at = datetime.utcnow()
        await self._checkpoint_session(session)

        # Start heartbeat scheduler for orchestrated protocols
        if session.heartbeat_enabled and session.protocol_stack_config and self._start_heartbeat:
            await self._start_heartbeat(session)

        # Start fuzzing task via callback
        if self._on_session_start:
            task = self._on_session_start(session)
            self.active_tasks[session_id] = task

        logger.info("session_started", session_id=session_id)
        return True

    async def stop_session(self, session_id: str) -> bool:
        """
        Stop a fuzzing session.

        Args:
            session_id: Session ID to stop

        Returns:
            True if stopped successfully
        """
        session = self.sessions.get(session_id)
        if not session:
            return False

        # Stop heartbeat if running
        if self._heartbeat_scheduler:
            self._heartbeat_scheduler.stop(session_id)

        # Run teardown stages for orchestrated protocols
        if session.protocol_stack_config and self._run_teardown:
            try:
                await self._run_teardown(session)
            except Exception as e:
                teardown_error = f"Teardown warning: {str(e)}"
                if session.error_message:
                    session.error_message = f"{session.error_message}\n{teardown_error}"
                else:
                    session.error_message = teardown_error
                logger.warning("teardown_failed", session_id=session.id, error=str(e))

        session.status = FuzzSessionStatus.COMPLETED
        session.completed_at = datetime.utcnow()
        await self._checkpoint_session(session)

        # Cancel task if running
        if session_id in self.active_tasks:
            task = self.active_tasks[session_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self.active_tasks[session_id]

        await self._cleanup_session_resources(session_id, session)

        # Flush pending execution records
        await self.history_store.flush()

        logger.info("session_stopped", session_id=session_id)
        return True

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and clean up resources.

        Args:
            session_id: Session ID to delete

        Returns:
            True if deleted successfully
        """
        session = self.sessions.get(session_id)
        if not session:
            return False

        # Stop the session if it's running
        if session.status == FuzzSessionStatus.RUNNING:
            await self.stop_session(session_id)
        else:
            await self._cleanup_session_resources(session_id, session)

        # Remove from sessions dict
        del self.sessions[session_id]

        # Remove from persistence database
        self.session_store.delete_session(session_id)

        logger.info("session_deleted", session_id=session_id)
        return True

    def get_session(self, session_id: str) -> Optional[FuzzSession]:
        """Get session by ID."""
        return self.sessions.get(session_id)

    def list_sessions(self) -> List[FuzzSession]:
        """List all sessions."""
        return list(self.sessions.values())

    def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session statistics."""
        session = self.sessions.get(session_id)
        if not session:
            return None

        findings = self.corpus_store.list_findings(session_id)
        ctx = self.context_manager.get_context(session_id)

        stats = {
            "session_id": session_id,
            "status": session.status.value,
            "total_tests": session.total_tests,
            "crashes": session.crashes,
            "hangs": session.hangs,
            "anomalies": session.anomalies,
            "findings_count": len(findings),
            "runtime_seconds": (
                (datetime.utcnow() - session.started_at).total_seconds()
                if session.started_at
                else 0
            ),
        }

        # Add state coverage if using stateful fuzzing
        if ctx and ctx.stateful_session:
            stats["state_coverage"] = ctx.stateful_session.get_coverage_stats()

        return stats

    async def _checkpoint_session(self, session: FuzzSession) -> bool:
        """Save session state to disk."""
        try:
            ctx = self.context_manager.get_context(session.id)
            if ctx and ctx.protocol_context:
                session.context = ctx.protocol_context.snapshot()
            self.session_store.save_session(session)
            return True
        except Exception as e:
            logger.error("session_checkpoint_failed", session_id=session.id, error=str(e))
            return False

    async def _cleanup_session_resources(
        self,
        session_id: str,
        session: Optional[FuzzSession] = None,
    ) -> None:
        """Clean up all resources associated with a session."""
        await agent_manager.clear_session(session_id)

        # Get context for coverage snapshot
        ctx = self.context_manager.get_context(session_id)
        if session and ctx and ctx.stateful_session:
            session.coverage_snapshot = ctx.stateful_session.get_coverage_stats()

        # Clean up context
        self.context_manager.cleanup_context(session_id)

        # Reset history
        self.history_store.reset_session(session_id)

        # Clean up connection
        if self._connection_manager:
            await self._connection_manager.close_session(session_id)

    def load_sessions_from_disk(self) -> List[FuzzSession]:
        """
        Load sessions from disk on startup.

        Returns:
            List of recovered sessions
        """
        recovered_sessions = self.session_store.load_all_sessions(status_filter=None)

        for session in recovered_sessions:
            # Mark running sessions as paused
            if session.status == FuzzSessionStatus.RUNNING:
                session.status = FuzzSessionStatus.PAUSED
                session.error_message = (
                    "Session was interrupted (container restart). "
                    "Review state and resume manually if needed."
                )

            # Rebuild runtime helpers for active sessions
            active_statuses = [
                FuzzSessionStatus.IDLE,
                FuzzSessionStatus.RUNNING,
                FuzzSessionStatus.PAUSED,
            ]
            if session.status in active_statuses:
                try:
                    self._rebuild_runtime_helpers(session)
                except Exception as e:
                    session.status = FuzzSessionStatus.FAILED
                    session.error_message = (
                        f"Recovery failed: {str(e)}. "
                        "Delete this session and recreate it."
                    )
                    logger.error(
                        "runtime_helper_rebuild_failed",
                        session_id=session.id,
                        protocol=session.protocol,
                        error=str(e),
                    )

            self.sessions[session.id] = session
            logger.info(
                "session_recovered_from_disk",
                session_id=session.id,
                protocol=session.protocol,
                status=session.status.value,
            )

        if recovered_sessions:
            logger.info("sessions_recovery_complete", count=len(recovered_sessions))

        return recovered_sessions

    def _rebuild_runtime_helpers(self, session: FuzzSession) -> None:
        """Rebuild runtime helpers for a recovered session."""
        protocol = plugin_manager.load_plugin(session.protocol)
        if not protocol:
            raise ValueError(f"Protocol '{session.protocol}' not found")

        ctx = self.context_manager.create_context(session.id)

        # Rebuild data models
        resolved_data_model = denormalize_data_model_from_json(protocol.data_model)
        ctx.data_model = resolved_data_model

        if protocol.response_model:
            ctx.response_model = denormalize_data_model_from_json(protocol.response_model)

        # Rebuild behavior processor
        behavior_processor = build_behavior_processor(resolved_data_model)
        if behavior_processor.has_behaviors():
            ctx.behavior_processor = behavior_processor

        # Rebuild response planner
        if protocol.response_handlers:
            from core.engine.response_planner import ResponsePlanner
            ctx.response_planner = ResponsePlanner(
                resolved_data_model,
                ctx.response_model,
                protocol.response_handlers,
            )
            ctx.followup_queue = deque()

        # Restore protocol context
        if session.context:
            from core.engine.protocol_context import ProtocolContext
            context = ProtocolContext()
            context.restore(session.context)
            ctx.protocol_context = context

    def _resolve_mutators(self, config: FuzzConfig) -> List[str]:
        """Translate config into concrete mutator names."""
        if config.enabled_mutators:
            return config.enabled_mutators

        from core.engine.mutators import MutationEngine

        mapping = {
            "bitflip": "bitflip",
            "byte_flip": "byteflip",
            "arithmetic": "arithmetic",
            "interesting_values": "interesting",
            "havoc": "havoc",
            "splice": "splice",
        }

        enabled = []
        strategy = config.mutation_strategy
        for key, name in mapping.items():
            if getattr(strategy, key, False):
                enabled.append(name)

        return enabled or MutationEngine.available_mutators()
