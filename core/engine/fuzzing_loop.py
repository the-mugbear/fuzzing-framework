"""
Fuzzing Loop Coordinator - Manages the main fuzzing loop.

This module implements the core fuzzing iteration loop, coordinating
test case generation, execution, and result processing.

Component Overview:
-------------------
The FuzzingLoopCoordinator is the heart of the fuzzing engine, managing:
- Context initialization (seeds, mutation engine, stateful session)
- Seed selection based on fuzzing mode and state
- Test case generation with mutation strategies
- Test execution via TestExecutor
- Result processing and crash handling
- Rate limiting and checkpointing

Key Responsibilities:
--------------------
1. Loop Initialization:
   - Load protocol plugin and data model
   - Initialize seed corpus from session
   - Create mutation engine with configured mutators
   - Setup stateful fuzzing if protocol has state_model

2. Seed Selection:
   - Use StateNavigator for stateful protocols
   - Handle termination test injection
   - Fall back to round-robin for simple protocols

3. Test Case Generation:
   - Apply mutation engine to selected seed
   - Enforce message type for stateful consistency
   - Track field mutation counts
   - Inject protocol context values
   - Apply behavior processors

4. Execution Coordination:
   - Route to TestExecutor (Core mode) or AgentDispatcher (Agent mode)
   - Record execution history with timing
   - Process response followups

5. State Management:
   - Update stateful session state
   - Handle periodic resets
   - Checkpoint session periodically

6. Error Handling:
   - Initialization failures -> FAILED status
   - Loop errors -> FAILED status with traceback
   - Cancellation -> clean shutdown

Integration Points:
------------------
- Uses TestExecutor for test execution
- Uses StateNavigator for state-aware seed selection
- Uses MutationEngine for test case generation
- Uses CorpusStore for seed access
- Uses CrashReporter for crash persistence
- Uses ExecutionHistoryStore for history recording

Usage Example:
-------------
    # Create coordinator
    coordinator = FuzzingLoopCoordinator(
        corpus_store=corpus_store,
        crash_reporter=crash_reporter,
        history_store=history_store,
        test_executor=executor,
    )

    # Set callbacks
    coordinator.set_callbacks(
        on_checkpoint=save_session_state,
        apply_behaviors=apply_computed_fields,
        inject_context=inject_session_tokens,
    )

    # Run fuzzing loop
    await coordinator.run(session, context)

Loop Flow:
---------
1. Initialize context (seeds, mutation engine, stateful session)
2. While session is RUNNING:
   a. Check for followup items from response planning
   b. Select seed and generate test case
   c. Execute test case
   d. Update state for stateful protocols
   e. Checkpoint periodically
   f. Apply rate limiting
3. Final cleanup and checkpoint

Note:
----
This module is part of the Phase 5 orchestrator decomposition. It extracts
the main fuzzing loop into a focused, testable component.

See Also:
--------
- core/engine/test_executor.py - Test execution
- core/engine/state_navigator.py - State-aware navigation
- core/engine/mutators.py - Mutation engine
- core/engine/session_context.py - Runtime context
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple, TYPE_CHECKING

import structlog

from core.agents.manager import agent_manager
from core.config import settings
from core.exceptions import PluginError, SessionInitializationError
from core.engine.mutators import MutationEngine
from core.engine.session_context import SessionRuntimeContext
from core.engine.state_navigator import StateNavigator
from core.engine.test_executor import TestExecutor
from core.models import (
    ExecutionMode,
    FuzzSession,
    FuzzSessionStatus,
    TestCase,
    TestCaseResult,
)
from core.plugin_loader import denormalize_data_model_from_json, plugin_manager

if TYPE_CHECKING:
    from core.corpus.store import CorpusStore
    from core.engine.crash_handler import CrashReporter
    from core.engine.history_store import ExecutionHistoryStore
    from core.engine.stateful_fuzzer import StatefulFuzzingSession

logger = structlog.get_logger()


class FuzzingLoopCoordinator:
    """
    Coordinates the main fuzzing loop for a session.

    Handles:
    - Fuzzing context initialization (seeds, mutation engine, stateful session)
    - Seed selection based on fuzzing mode
    - Test case generation with mutations
    - Test execution and result processing
    - State tracking for stateful fuzzing
    - Rate limiting and checkpointing

    This component is designed to work with SessionRuntimeContext and
    can be integrated with the orchestrator or used standalone.
    """

    def __init__(
        self,
        corpus_store: "CorpusStore",
        crash_reporter: "CrashReporter",
        history_store: "ExecutionHistoryStore",
        test_executor: Optional[TestExecutor] = None,
    ):
        """
        Initialize the FuzzingLoopCoordinator.

        Args:
            corpus_store: CorpusStore for seed management
            crash_reporter: CrashReporter for recording crashes
            history_store: ExecutionHistoryStore for execution history
            test_executor: Optional TestExecutor (created if not provided)
        """
        self.corpus_store = corpus_store
        self.crash_reporter = crash_reporter
        self.history_store = history_store
        self.test_executor = test_executor or TestExecutor()

        # Pending tests for agent mode
        self.pending_tests: Dict[str, TestCase] = {}

        # Callbacks
        self._on_checkpoint: Optional[Callable[[FuzzSession], Any]] = None
        self._apply_behaviors: Optional[Callable[[FuzzSession, bytes], bytes]] = None
        self._inject_context: Optional[Callable[[FuzzSession, bytes], bytes]] = None

    def set_callbacks(
        self,
        on_checkpoint: Optional[Callable[[FuzzSession], Any]] = None,
        apply_behaviors: Optional[Callable[[FuzzSession, bytes], bytes]] = None,
        inject_context: Optional[Callable[[FuzzSession, bytes], bytes]] = None,
    ) -> None:
        """Set callbacks for orchestrator integration."""
        self._on_checkpoint = on_checkpoint
        self._apply_behaviors = apply_behaviors
        self._inject_context = inject_context

    async def run(
        self,
        session: FuzzSession,
        context: SessionRuntimeContext,
    ) -> None:
        """
        Run the main fuzzing loop for a session.

        Args:
            session: The fuzzing session
            context: The session's runtime context
        """
        session_id = session.id
        logger.info(
            "fuzzing_loop_started",
            session_id=session_id,
            execution_mode=session.execution_mode,
        )

        # Initialize fuzzing context
        try:
            seeds, mutation_engine, stateful_session = await self._initialize_context(
                session, context
            )
        except (SessionInitializationError, PluginError) as e:
            logger.error(
                "initialization_failed",
                session_id=session_id,
                error=str(e),
            )
            session.status = FuzzSessionStatus.FAILED
            session.error_message = str(e)
            await self._checkpoint(session)
            return

        # Create state navigator if stateful
        state_navigator = None
        if stateful_session:
            state_navigator = StateNavigator(stateful_session, session)
            context.stateful_session = stateful_session

        try:
            await self._run_loop(
                session, context, seeds, mutation_engine, state_navigator
            )
        except asyncio.CancelledError:
            logger.info("fuzzing_loop_cancelled", session_id=session_id)
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            logger.error(
                "fuzzing_loop_error",
                session_id=session_id,
                error=str(e),
                error_type=type(e).__name__,
                traceback=error_traceback,
            )
            session.status = FuzzSessionStatus.FAILED
            session.error_message = f"Fuzzing error: {type(e).__name__}: {str(e)}"
            await self._checkpoint(session)
        finally:
            if session.execution_mode == ExecutionMode.AGENT:
                await agent_manager.clear_session(session_id)
            self._discard_pending_tests(session_id)
            if stateful_session:
                session.coverage_snapshot = stateful_session.get_coverage_stats()
            await self._checkpoint(session)

    async def _run_loop(
        self,
        session: FuzzSession,
        context: SessionRuntimeContext,
        seeds: List[bytes],
        mutation_engine: MutationEngine,
        state_navigator: Optional[StateNavigator],
    ) -> None:
        """Run the main iteration loop."""
        session_id = session.id
        iteration = session.total_tests

        if iteration > 0:
            logger.info(
                "resuming_from_iteration",
                session_id=session_id,
                starting_iteration=iteration,
            )

        # Calculate rate limiting parameters
        rate_limit_delay = None
        if session.rate_limit_per_second and session.rate_limit_per_second > 0:
            rate_limit_delay = 1.0 / session.rate_limit_per_second

        while session.status == FuzzSessionStatus.RUNNING:
            loop_start = time.time()

            # Check for followup items
            followup_item = self._get_followup_item(
                session, context, state_navigator, iteration
            )

            if followup_item:
                test_case = self._create_followup_test_case(
                    session, context, followup_item
                )
            else:
                test_case = self._create_fuzz_test_case(
                    session, context, seeds, mutation_engine, state_navigator, iteration
                )

            # Execute and record test case
            result, response = await self._execute_and_record(
                session, context, test_case, state_navigator
            )

            # Update stateful fuzzing state
            if state_navigator and session.execution_mode == ExecutionMode.CORE:
                state_navigator.update_state(
                    session, test_case.data, response, result, iteration
                )

            iteration += 1

            # Periodic checkpoint
            if iteration % settings.checkpoint_frequency == 0:
                await self._checkpoint(session)

            # Check iteration limit
            if session.max_iterations and iteration >= session.max_iterations:
                session.status = FuzzSessionStatus.COMPLETED
                session.completed_at = datetime.utcnow()
                await self._checkpoint(session)
                break

            # Rate limiting
            if rate_limit_delay:
                elapsed = time.time() - loop_start
                if elapsed < rate_limit_delay:
                    await asyncio.sleep(rate_limit_delay - elapsed)
            else:
                await asyncio.sleep(0.001)

    async def _initialize_context(
        self,
        session: FuzzSession,
        context: SessionRuntimeContext,
    ) -> Tuple[List[bytes], MutationEngine, Optional["StatefulFuzzingSession"]]:
        """
        Initialize fuzzing context for a session.

        Returns:
            Tuple of (seeds, mutation_engine, stateful_session)
        """
        # Load protocol
        try:
            protocol = plugin_manager.load_plugin(session.protocol)
        except Exception as e:
            raise PluginError(f"Failed to load protocol '{session.protocol}': {str(e)}")

        data_model = context.data_model
        if protocol and not data_model:
            data_model = denormalize_data_model_from_json(protocol.data_model)
            context.data_model = data_model

        # Load seeds
        seeds = [self.corpus_store.get_seed(sid) for sid in session.seed_corpus]
        seeds = [s for s in seeds if s is not None]

        if not seeds:
            raise SessionInitializationError(
                "No seeds available for fuzzing",
                details={"session_id": session.id, "seed_corpus": session.seed_corpus},
            )

        # Initialize mutation engine
        mutation_engine = MutationEngine(
            seeds,
            enabled_mutators=session.enabled_mutators,
            data_model=data_model,
            mutation_mode=session.mutation_mode,
            structure_aware_weight=session.structure_aware_weight,
        )

        # Setup stateful fuzzing if applicable
        stateful_session = None
        if protocol and protocol.state_model:
            from core.engine.stateful_fuzzer import StatefulFuzzingSession

            transitions = protocol.state_model.get("transitions", [])
            if transitions:
                response_model = None
                if protocol.response_model:
                    response_model = denormalize_data_model_from_json(protocol.response_model)

                stateful_session = StatefulFuzzingSession(
                    protocol.state_model,
                    data_model or denormalize_data_model_from_json(protocol.data_model),
                    response_model=response_model,
                )

                # Restore state if resuming
                if session.current_state or session.state_coverage or session.transition_coverage:
                    stateful_session.restore_state(
                        current_state=session.current_state,
                        state_history=None,
                        state_coverage=session.state_coverage,
                        transition_coverage=session.transition_coverage,
                    )

                logger.info(
                    "stateful_fuzzing_enabled",
                    session_id=session.id,
                    initial_state=stateful_session.current_state,
                    num_transitions=len(transitions),
                )

        return seeds, mutation_engine, stateful_session

    def _get_followup_item(
        self,
        session: FuzzSession,
        context: SessionRuntimeContext,
        state_navigator: Optional[StateNavigator],
        iteration: int,
    ) -> Optional[Dict]:
        """Get a followup item from the queue if available."""
        if not context.followup_queue:
            return None

        # Check if we should skip followup for termination test
        if state_navigator and state_navigator.should_inject_termination_test(
            session, iteration
        ):
            return None

        try:
            return context.followup_queue.popleft()
        except IndexError:
            return None

    def _create_followup_test_case(
        self,
        session: FuzzSession,
        context: SessionRuntimeContext,
        followup_item: Dict,
    ) -> TestCase:
        """Create a test case from a followup item."""
        payload = followup_item["payload"]

        # Apply behaviors
        if self._apply_behaviors:
            payload = self._apply_behaviors(session, payload)

        test_case = TestCase(
            id=str(uuid.uuid4()),
            session_id=session.id,
            data=payload,
            seed_id=None,
            mutation_strategy="response_followup",
            mutators_applied=["followup"],
        )

        logger.info(
            "followup_dispatched",
            session_id=session.id,
            handler=followup_item.get("handler"),
        )

        return test_case

    def _create_fuzz_test_case(
        self,
        session: FuzzSession,
        context: SessionRuntimeContext,
        seeds: List[bytes],
        mutation_engine: MutationEngine,
        state_navigator: Optional[StateNavigator],
        iteration: int,
    ) -> TestCase:
        """Create a mutated test case."""
        # Select seed
        base_seed = self._select_seed(
            session, seeds, state_navigator, iteration
        )

        # Generate mutated data
        test_case_data = mutation_engine.generate_test_case(base_seed)
        mutation_meta = mutation_engine.get_last_metadata()

        # Enforce message type for stateful sessions
        if state_navigator and state_navigator.stateful_session.message_type_field:
            test_case_data = self._enforce_message_type(
                state_navigator.stateful_session, base_seed, test_case_data
            )

        # Track field mutations
        if mutation_meta.get("field"):
            field_name = mutation_meta["field"]
            session.field_mutation_counts[field_name] = (
                session.field_mutation_counts.get(field_name, 0) + 1
            )

        # Inject context values
        if self._inject_context:
            test_case_data = self._inject_context(session, test_case_data)

        # Apply behaviors
        if self._apply_behaviors:
            test_case_data = self._apply_behaviors(session, test_case_data)

        # Determine seed reference
        seed_reference = (
            session.seed_corpus[iteration % len(session.seed_corpus)]
            if session.seed_corpus
            else None
        )

        return TestCase(
            id=str(uuid.uuid4()),
            session_id=session.id,
            data=test_case_data,
            seed_id=seed_reference,
            mutation_strategy=mutation_meta.get("strategy"),
            mutators_applied=mutation_meta.get("mutators", []),
        )

    def _select_seed(
        self,
        session: FuzzSession,
        seeds: List[bytes],
        state_navigator: Optional[StateNavigator],
        iteration: int,
    ) -> bytes:
        """Select appropriate seed for current iteration."""
        if not state_navigator:
            return seeds[iteration % len(seeds)]

        # Check for termination test injection
        if state_navigator.should_inject_termination_test(session, iteration):
            termination_seed = state_navigator.select_termination_message(session, seeds)
            if termination_seed:
                return termination_seed

        # Select based on fuzzing mode
        base_seed = state_navigator.select_message_for_mode(session, seeds, iteration)

        if base_seed is None:
            # Fallback to standard stateful selection
            message_type = state_navigator.stateful_session.get_message_type_for_state()

            if message_type is None:
                state_navigator.reset()
                message_type = state_navigator.stateful_session.get_message_type_for_state()

            base_seed = state_navigator.stateful_session.find_seed_for_message_type(
                message_type, seeds
            )

            if base_seed is None:
                base_seed = seeds[iteration % len(seeds)]

        return base_seed

    def _enforce_message_type(
        self,
        stateful_session: "StatefulFuzzingSession",
        base_seed: bytes,
        mutated_data: bytes,
    ) -> bytes:
        """Ensure message_type remains consistent with the selected seed."""
        if not stateful_session.message_type_field:
            return mutated_data

        try:
            base_fields = stateful_session.parser.parse(base_seed)
            desired_value = base_fields.get(stateful_session.message_type_field)
            if desired_value is None:
                return mutated_data

            mutated_fields = stateful_session.parser.parse(mutated_data)
            mutated_fields[stateful_session.message_type_field] = desired_value
            return stateful_session.parser.serialize(mutated_fields)
        except Exception as e:
            logger.debug("message_type_enforcement_failed", error=str(e))
            return mutated_data

    async def _execute_and_record(
        self,
        session: FuzzSession,
        context: SessionRuntimeContext,
        test_case: TestCase,
        state_navigator: Optional[StateNavigator],
    ) -> Tuple[TestCaseResult, Optional[bytes]]:
        """Execute test case and record results."""
        if session.execution_mode == ExecutionMode.AGENT:
            await self._dispatch_to_agent(session, test_case)
            return TestCaseResult.PASS, None

        # Capture state info before execution
        message_type = None
        state_at_send = None
        if state_navigator:
            message_type = state_navigator.stateful_session.identify_message_type(test_case.data)
            state_at_send = state_navigator.current_state

        # Execute with timing
        timestamp_sent = datetime.utcnow()
        result, response = await self.test_executor.execute(session, test_case)
        timestamp_response = datetime.utcnow()

        # Finalize test case
        await self._finalize_test_case(session, test_case, result, response)

        # Get context snapshot
        context_snapshot = context.get_context_snapshot()

        # Record execution
        self.history_store.record(
            session,
            test_case,
            timestamp_sent,
            timestamp_response,
            result,
            response,
            message_type=message_type,
            state_at_send=state_at_send,
            context_snapshot=context_snapshot,
        )

        # Evaluate response followups
        if response and context.response_planner:
            followups = context.response_planner.plan_followups(response)
            for followup in followups:
                context.followup_queue.append(followup)

        return result, response

    async def _dispatch_to_agent(
        self,
        session: FuzzSession,
        test_case: TestCase,
    ) -> None:
        """Send a test case to the agent queue."""
        from core.models import AgentWorkItem

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
        self.pending_tests[test_case.id] = test_case
        await agent_manager.enqueue_test_case(
            session.target_host,
            session.target_port,
            session.transport,
            work,
        )

    async def _finalize_test_case(
        self,
        session: FuzzSession,
        test_case: TestCase,
        result: TestCaseResult,
        response: Optional[bytes] = None,
    ) -> None:
        """Update session statistics and persist findings."""
        session.total_tests += 1
        test_case.result = result

        if result == TestCaseResult.CRASH:
            session.crashes += 1
            crash_report = self.crash_reporter.report(
                session,
                test_case,
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

    def _discard_pending_tests(self, session_id: str) -> None:
        """Discard pending tests for a session."""
        to_remove = [
            tid for tid, tc in self.pending_tests.items()
            if tc.session_id == session_id
        ]
        for tid in to_remove:
            del self.pending_tests[tid]

    async def _checkpoint(self, session: FuzzSession) -> None:
        """Save session checkpoint."""
        if self._on_checkpoint:
            await self._on_checkpoint(session)
