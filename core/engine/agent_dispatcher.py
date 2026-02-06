"""
Agent Dispatcher - Manages work distribution to remote agents.

This module handles the coordination of test case execution when using
remote agents instead of direct Core-based execution.

Component Overview:
-------------------
The AgentDispatcher manages the full lifecycle of agent-based test execution:
- Packaging test cases as AgentWorkItems
- Queueing work for specific agents
- Tracking pending test cases
- Processing results when agents report back
- Cleaning up on session stop

Key Responsibilities:
--------------------
1. Test Case Dispatch:
   - Create AgentWorkItem with all necessary context
   - Queue work item for target-specific agent
   - Track pending test case for result correlation

2. Result Processing:
   - Match incoming results to pending test cases
   - Update session statistics (crashes, hangs, anomalies)
   - Trigger crash reporter for crash results
   - Record execution history if callback provided

3. Session Cleanup:
   - Discard pending tests when session stops
   - Clear all pending on shutdown
   - Provide statistics about pending work

4. Integration Callbacks:
   - on_finalize: Custom finalization logic
   - record_execution: History store integration
   - crash_reporter: Crash persistence

Integration Points:
------------------
- Uses agent_manager for queue operations
- Uses CrashReporter for crash persistence
- Uses ExecutionHistoryStore for history recording
- Integrates with FuzzOrchestrator via callbacks

Usage Example:
-------------
    # Create dispatcher with dependencies
    dispatcher = AgentDispatcher(
        crash_reporter=crash_reporter,
        history_store=history_store,
    )

    # Dispatch test case to agent
    await dispatcher.dispatch(session, test_case)

    # Handle result when agent reports back
    status = await dispatcher.handle_result(
        agent_id="agent-1",
        payload=agent_result,
        session=session,
    )

    # Clean up on session stop
    discarded = dispatcher.discard_pending(session_id)

Agent Work Item Structure:
-------------------------
AgentWorkItem contains:
- session_id: For result correlation
- test_case_id: Unique test identifier
- protocol: Protocol name for validation
- target_host/port: Where to send test
- transport: TCP/UDP/etc
- data: The actual test bytes
- timeout_ms: Execution timeout

Note:
----
This module is part of the Phase 5 orchestrator decomposition. It extracts
agent coordination into a focused, testable component.

See Also:
--------
- core/agents/manager.py - Agent queue management
- core/models.py - AgentWorkItem, AgentTestResult definitions
- docs/developer/05_agent_and_core_communication.md - Agent architecture
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

import structlog

from core.agents.manager import agent_manager
from core.models import (
    AgentTestResult,
    AgentWorkItem,
    FuzzSession,
    TestCase,
    TestCaseResult,
)

if TYPE_CHECKING:
    from core.engine.crash_handler import CrashReporter
    from core.engine.history_store import ExecutionHistoryStore

logger = structlog.get_logger()


class AgentDispatcher:
    """
    Coordinates work distribution to remote agents.

    Handles:
    - Test case dispatch to agent queues
    - Result collection from agents
    - Pending test case tracking
    - Session cleanup on stop

    This component can be used standalone or integrated with the orchestrator.
    """

    def __init__(
        self,
        crash_reporter: Optional["CrashReporter"] = None,
        history_store: Optional["ExecutionHistoryStore"] = None,
        on_finalize: Optional[Callable[[FuzzSession, TestCase, TestCaseResult, Optional[bytes], Dict], None]] = None,
    ):
        """
        Initialize the AgentDispatcher.

        Args:
            crash_reporter: Optional CrashReporter for recording crashes
            history_store: Optional ExecutionHistoryStore for recording executions
            on_finalize: Optional callback for test case finalization
        """
        self._pending_tests: Dict[str, TestCase] = {}
        self._crash_reporter = crash_reporter
        self._history_store = history_store
        self._on_finalize = on_finalize

    @property
    def pending_count(self) -> int:
        """Get count of pending test cases."""
        return len(self._pending_tests)

    def get_pending_test(self, test_case_id: str) -> Optional[TestCase]:
        """Get a pending test case by ID."""
        return self._pending_tests.get(test_case_id)

    async def dispatch(
        self,
        session: FuzzSession,
        test_case: TestCase,
    ) -> None:
        """
        Send a test case to the agent queue.

        Args:
            session: The fuzzing session
            test_case: The test case to dispatch
        """
        work = AgentWorkItem(
            session_id=session.id,
            test_case_id=test_case.id,
            protocol=session.protocol,
            target_host=session.target_host,
            target_port=session.target_port,
            transport=session.transport,
            data=test_case.data,
            timeout_ms=session.timeout_per_test_ms,
        )

        self._pending_tests[test_case.id] = test_case

        await agent_manager.enqueue_test_case(
            session.target_host,
            session.target_port,
            session.transport,
            work,
        )

        logger.debug(
            "test_case_dispatched",
            session_id=session.id,
            test_case_id=test_case.id,
        )

    async def handle_result(
        self,
        agent_id: str,
        payload: AgentTestResult,
        session: FuzzSession,
        context_snapshot: Optional[Dict[str, Any]] = None,
        parsed_fields: Optional[Dict[str, Any]] = None,
        record_execution: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Handle results coming back from an agent.

        Args:
            agent_id: The agent that executed the test
            payload: The test result payload
            session: The fuzzing session
            context_snapshot: Optional protocol context snapshot
            parsed_fields: Optional parsed field values
            record_execution: Optional callback to record execution history

        Returns:
            Status dict with result information
        """
        if not session:
            await agent_manager.complete_work(payload.test_case_id)
            logger.error("agent_result_unknown_session", session_id=payload.session_id)
            return {"status": "unknown_session"}

        test_case = self._pending_tests.pop(payload.test_case_id, None)
        if not test_case:
            await agent_manager.complete_work(payload.test_case_id)
            logger.warning(
                "agent_result_missing_test",
                test_case_id=payload.test_case_id,
                session_id=payload.session_id,
            )
            return {"status": "stale"}

        response_bytes = payload.response if payload.response else None
        test_case.execution_time_ms = payload.execution_time_ms

        # Finalize the test case
        await self._finalize_test_case(
            session,
            test_case,
            payload.result,
            response=response_bytes,
            metrics={
                "cpu_usage": payload.cpu_usage or 0.0,
                "memory_usage_mb": payload.memory_usage_mb or 0.0,
            },
        )

        # Record execution history if callback provided
        if record_execution:
            timestamp_response = datetime.utcnow()
            duration_ms = payload.execution_time_ms or 0.0
            timestamp_sent = timestamp_response - timedelta(milliseconds=duration_ms)

            record_execution(
                session,
                test_case,
                timestamp_sent,
                timestamp_response,
                payload.result,
                response_bytes,
                context_snapshot=context_snapshot,
                parsed_fields=parsed_fields,
            )

        await agent_manager.complete_work(payload.test_case_id)

        logger.debug(
            "agent_result_processed",
            agent_id=agent_id,
            session_id=session.id,
            test_case_id=test_case.id,
            result=payload.result.value if payload.result else "unknown",
        )

        return {"status": "ok"}

    async def _finalize_test_case(
        self,
        session: FuzzSession,
        test_case: TestCase,
        result: TestCaseResult,
        response: Optional[bytes] = None,
        metrics: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Update session statistics and persist findings.

        Args:
            session: The fuzzing session
            test_case: The test case
            result: Test result
            response: Response from target
            metrics: Execution metrics (cpu_usage, memory_usage_mb)
        """
        metrics = metrics or {}
        session.total_tests += 1
        test_case.result = result

        if result == TestCaseResult.CRASH:
            session.crashes += 1
            if self._crash_reporter:
                crash_report = self._crash_reporter.report(
                    session,
                    test_case,
                    cpu_usage=metrics.get("cpu_usage"),
                    memory_usage=metrics.get("memory_usage_mb"),
                    response=response,
                )
                logger.warning(
                    "crash_detected",
                    session_id=session.id,
                    finding_id=crash_report.id,
                    test_case_id=test_case.id,
                )
        elif result == TestCaseResult.HANG:
            session.hangs += 1
        elif result in (TestCaseResult.ANOMALY, TestCaseResult.LOGICAL_FAILURE):
            session.anomalies += 1

        # Call custom finalization callback if provided
        if self._on_finalize:
            self._on_finalize(session, test_case, result, response, metrics)

    def discard_pending(self, session_id: str) -> int:
        """
        Discard all pending tests for a session.

        Args:
            session_id: The session ID

        Returns:
            Number of tests discarded
        """
        to_remove = [
            tid for tid, tc in self._pending_tests.items()
            if tc.session_id == session_id
        ]

        for tid in to_remove:
            del self._pending_tests[tid]

        if to_remove:
            logger.debug(
                "pending_tests_discarded",
                session_id=session_id,
                count=len(to_remove),
            )

        return len(to_remove)

    def clear_all(self) -> None:
        """Clear all pending tests."""
        count = len(self._pending_tests)
        self._pending_tests.clear()
        logger.debug("all_pending_tests_cleared", count=count)

    def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics."""
        sessions = {}
        for tc in self._pending_tests.values():
            sessions[tc.session_id] = sessions.get(tc.session_id, 0) + 1

        return {
            "total_pending": len(self._pending_tests),
            "sessions_with_pending": len(sessions),
            "pending_by_session": sessions,
        }
