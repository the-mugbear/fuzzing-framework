"""
Session Runtime Context - Manages per-session runtime state.

This module provides centralized management of session-specific runtime helpers
and transient state that exists only while a fuzzing session is active.

Component Overview:
-------------------
The SessionContextManager and SessionRuntimeContext work together to consolidate
what was previously scattered across multiple dictionaries in the orchestrator:
- behavior_processors (computed field processors)
- stateful_sessions (state machine tracking)
- response_planners (followup message generation)
- protocol_contexts (orchestrated session state)
- data_models (resolved protocol definitions)

Key Responsibilities:
--------------------
1. Runtime State Container (SessionRuntimeContext):
   - Holds all transient helpers for a single session
   - Provides convenience methods for checking capabilities
   - Handles cleanup when session ends

2. Context Lifecycle Management (SessionContextManager):
   - Creates contexts when sessions start
   - Provides access to contexts by session ID
   - Cleans up contexts when sessions stop/delete
   - Tracks statistics about active contexts

Integration Points:
------------------
- Used by SessionManager during session creation/deletion
- Used by FuzzingLoopCoordinator during test execution
- Used by FuzzOrchestrator for backward compatibility

Usage Example:
-------------
    # Create manager
    manager = SessionContextManager()

    # Create context for new session
    ctx = manager.create_context(session_id="abc-123")
    ctx.data_model = resolved_data_model
    ctx.behavior_processor = build_behavior_processor(data_model)

    # Access during fuzzing
    ctx = manager.get_context("abc-123")
    if ctx.has_behaviors():
        data = ctx.behavior_processor.apply(data)

    # Cleanup when done
    manager.cleanup_context("abc-123")

Note:
----
This module is part of the Phase 5 orchestrator decomposition. It extracts
runtime context management into a focused, testable component.

See Also:
--------
- core/engine/session_manager.py - Session lifecycle management
- core/engine/fuzzing_loop.py - Uses contexts during test execution
- docs/developer/01_architectural_overview.md - Architecture documentation
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from core.engine.protocol_context import ProtocolContext
    from core.engine.response_planner import ResponsePlanner
    from core.engine.stage_runner import StageRunner
    from core.engine.stateful_fuzzer import StatefulFuzzingSession

logger = structlog.get_logger()


@dataclass
class SessionRuntimeContext:
    """
    Container for all session-specific runtime state.

    Consolidates behavior processors, stateful sessions, response planners,
    and other runtime helpers that were previously tracked in separate
    dictionaries on the orchestrator.

    Attributes:
        session_id: The session this context belongs to
        behavior_processor: Processes protocol behaviors (computed fields, etc.)
        stateful_session: StatefulFuzzingSession for state machine tracking
        response_planner: Plans followup messages based on responses
        followup_queue: Queue of pending followup messages
        data_model: Resolved protocol data model
        response_model: Resolved response data model (optional)
        protocol_context: ProtocolContext for orchestrated sessions
        stage_runner: StageRunner for orchestrated sessions
    """

    session_id: str
    behavior_processor: Optional[Any] = None
    stateful_session: Optional["StatefulFuzzingSession"] = None
    response_planner: Optional["ResponsePlanner"] = None
    followup_queue: Deque = field(default_factory=deque)
    data_model: Optional[Dict[str, Any]] = None
    response_model: Optional[Dict[str, Any]] = None
    protocol_context: Optional["ProtocolContext"] = None
    stage_runner: Optional["StageRunner"] = None

    def has_behaviors(self) -> bool:
        """Check if this session has behavior processing enabled."""
        return (
            self.behavior_processor is not None
            and self.behavior_processor.has_behaviors()
        )

    def has_stateful_fuzzing(self) -> bool:
        """Check if this session has stateful fuzzing enabled."""
        return self.stateful_session is not None

    def has_response_planning(self) -> bool:
        """Check if this session has response planning enabled."""
        return self.response_planner is not None

    def has_orchestration(self) -> bool:
        """Check if this session uses orchestrated protocol stages."""
        return self.protocol_context is not None

    def get_context_snapshot(self) -> Optional[Dict[str, Any]]:
        """Get a snapshot of the protocol context if available."""
        if self.protocol_context:
            return self.protocol_context.snapshot()
        return None

    def cleanup(self) -> None:
        """Clean up runtime resources."""
        self.behavior_processor = None
        self.stateful_session = None
        self.response_planner = None
        self.followup_queue.clear()
        self.data_model = None
        self.response_model = None
        self.protocol_context = None
        self.stage_runner = None


class SessionContextManager:
    """
    Manages SessionRuntimeContext instances for all active sessions.

    Provides a unified interface for creating, accessing, and cleaning up
    session runtime contexts.
    """

    def __init__(self):
        self._contexts: Dict[str, SessionRuntimeContext] = {}

    def create_context(self, session_id: str) -> SessionRuntimeContext:
        """
        Create a new runtime context for a session.

        Args:
            session_id: The session ID

        Returns:
            New SessionRuntimeContext instance
        """
        if session_id in self._contexts:
            logger.warning(
                "overwriting_existing_context",
                session_id=session_id,
            )
            self._contexts[session_id].cleanup()

        context = SessionRuntimeContext(session_id=session_id)
        self._contexts[session_id] = context
        logger.debug("session_context_created", session_id=session_id)
        return context

    def get_context(self, session_id: str) -> Optional[SessionRuntimeContext]:
        """
        Get the runtime context for a session.

        Args:
            session_id: The session ID

        Returns:
            SessionRuntimeContext or None if not found
        """
        return self._contexts.get(session_id)

    def get_or_create_context(self, session_id: str) -> SessionRuntimeContext:
        """
        Get existing context or create a new one.

        Args:
            session_id: The session ID

        Returns:
            SessionRuntimeContext instance
        """
        if session_id not in self._contexts:
            return self.create_context(session_id)
        return self._contexts[session_id]

    def has_context(self, session_id: str) -> bool:
        """Check if a context exists for the session."""
        return session_id in self._contexts

    def cleanup_context(self, session_id: str) -> None:
        """
        Clean up and remove context for a session.

        Args:
            session_id: The session ID to clean up
        """
        if session_id in self._contexts:
            self._contexts[session_id].cleanup()
            del self._contexts[session_id]
            logger.debug("session_context_cleaned", session_id=session_id)

    def cleanup_all(self) -> None:
        """Clean up all contexts."""
        for context in self._contexts.values():
            context.cleanup()
        self._contexts.clear()
        logger.debug("all_session_contexts_cleaned")

    def list_sessions(self) -> list[str]:
        """Get list of session IDs with active contexts."""
        return list(self._contexts.keys())

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about managed contexts."""
        return {
            "total_contexts": len(self._contexts),
            "with_behaviors": sum(
                1 for c in self._contexts.values() if c.has_behaviors()
            ),
            "with_stateful": sum(
                1 for c in self._contexts.values() if c.has_stateful_fuzzing()
            ),
            "with_orchestration": sum(
                1 for c in self._contexts.values() if c.has_orchestration()
            ),
        }
