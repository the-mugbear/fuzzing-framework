"""
Fuzzing orchestrator - coordinates the fuzzing campaign
"""
import asyncio
import base64
import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog

from core.agents.manager import agent_manager
from core.config import settings
from core.corpus.store import CorpusStore
from core.exceptions import (
    SessionInitializationError,
    PluginError,
    TransportError,
    ConnectionRefusedError as FuzzerConnectionRefusedError,
    ConnectionTimeoutError,
    ReceiveTimeoutError,
)
from core.plugin_loader import decode_seeds_from_json, denormalize_data_model_from_json
from core.engine.crash_handler import CrashReporter
from core.engine.history_store import ExecutionHistoryStore
from core.engine.mutators import MutationEngine
from core.engine.response_planner import ResponsePlanner
from core.engine.stateful_fuzzer import StatefulFuzzingSession
from core.models import (
    AgentTestResult,
    AgentWorkItem,
    ExecutionMode,
    FuzzConfig,
    FuzzSession,
    FuzzSessionStatus,
    OneOffTestRequest,
    OneOffTestResult,
    TestCase,
    TestCaseExecutionRecord,
    TestCaseResult,
    TransportProtocol,
)
from core.plugin_loader import plugin_manager
from core.protocol_behavior import build_behavior_processor

logger = structlog.get_logger()


class FuzzOrchestrator:
    """
    Orchestrates fuzzing campaigns

    Manages sessions, coordinates mutation engine, corpus, and agents.
    """

    def __init__(self):
        self.corpus_store = CorpusStore()
        self.sessions: Dict[str, FuzzSession] = {}
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.pending_tests: Dict[str, TestCase] = {}
        self.behavior_processors: Dict[str, Any] = {}
        self.stateful_sessions: Dict[str, StatefulFuzzingSession] = {}  # Track stateful sessions
        self.response_planners: Dict[str, ResponsePlanner] = {}
        self.followup_queues: Dict[str, deque] = {}
        self.session_data_models: Dict[str, Dict[str, Any]] = {}
        self.session_response_models: Dict[str, Dict[str, Any]] = {}
        self.history_store = ExecutionHistoryStore()
        self.crash_reporter = CrashReporter(self.corpus_store)

        # Session persistence
        from core.engine.session_store import SessionStore
        self.session_store = SessionStore()
        self._load_sessions_from_disk()

    def _load_sessions_from_disk(self):
        """
        Load sessions from disk on startup.

        Loads all sessions for historical tracking. Sessions that were RUNNING are marked
        as PAUSED to allow manual resume. Rebuilds runtime helpers for active sessions.
        """
        # Load all sessions (including completed/failed for historical tracking)
        recovered_sessions = self.session_store.load_all_sessions(status_filter=None)

        for session in recovered_sessions:
            # Mark running sessions as paused (don't auto-resume)
            if session.status == FuzzSessionStatus.RUNNING:
                session.status = FuzzSessionStatus.PAUSED
                session.error_message = (
                    "Session was interrupted (container restart). "
                    "Review state and resume manually if needed."
                )

            # Rebuild runtime helpers only for active sessions (not completed/failed)
            # Completed/failed sessions are loaded for historical tracking only
            active_statuses = [FuzzSessionStatus.IDLE, FuzzSessionStatus.RUNNING, FuzzSessionStatus.PAUSED]
            if session.status in active_statuses:
                try:
                    protocol = plugin_manager.load_plugin(session.protocol)
                    if protocol:
                        # Rebuild behavior processor if protocol has behaviors
                        resolved_data_model = denormalize_data_model_from_json(protocol.data_model)
                        behavior_processor = build_behavior_processor(resolved_data_model)

                        if behavior_processor.has_behaviors():
                            self.behavior_processors[session.id] = behavior_processor
                            logger.debug(
                                "behavior_processor_rebuilt",
                                session_id=session.id,
                                protocol=session.protocol
                            )

                        # Rebuild response planner if protocol has response handlers
                        if protocol.response_handlers:
                            resolved_response_model = None
                            if protocol.response_model:
                                resolved_response_model = denormalize_data_model_from_json(protocol.response_model)

                            planner = ResponsePlanner(
                                resolved_data_model,
                                resolved_response_model,
                                protocol.response_handlers,
                            )
                            self.response_planners[session.id] = planner
                            self.followup_queues.setdefault(session.id, deque())
                            logger.debug(
                                "response_planner_rebuilt",
                                session_id=session.id,
                                protocol=session.protocol
                            )
                except Exception as e:
                    logger.error(
                        "runtime_helper_rebuild_failed",
                        session_id=session.id,
                        protocol=session.protocol,
                        error=str(e)
                    )

            self.sessions[session.id] = session
            logger.info(
                "session_recovered_from_disk",
                session_id=session.id,
                protocol=session.protocol,
                status=session.status.value,
                total_tests=session.total_tests,
            )

        if recovered_sessions:
            logger.info("sessions_recovery_complete", count=len(recovered_sessions))

    async def _checkpoint_session(self, session: FuzzSession):
        """
        Save session state to disk.

        Called periodically during fuzzing and on status changes.
        """
        try:
            self.session_store.save_session(session)
        except Exception as e:
            logger.error("session_checkpoint_failed", session_id=session.id, error=str(e))

    async def create_session(self, config: FuzzConfig) -> FuzzSession:
        """
        Create a new fuzzing session

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
        self.session_data_models[session_id] = resolved_data_model
        if resolved_response_model:
            self.session_response_models[session_id] = resolved_response_model
        session_transport = config.transport or protocol.transport

        # Initialize seed corpus from plugin
        seed_corpus = []
        if "seeds" in protocol.data_model:
            # Decode seeds from base64 (they're stored as base64 strings for JSON safety)
            seeds_bytes = decode_seeds_from_json(protocol.data_model["seeds"])
            for seed in seeds_bytes:
                seed_id = self.corpus_store.add_seed(
                    seed, metadata={"protocol": config.protocol, "source": "plugin"}
                )
                seed_corpus.append(seed_id)

        enabled_mutators = self._resolve_mutators(config)
        behavior_processor = build_behavior_processor(resolved_data_model)

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
            # NEW: Targeting configuration
            target_state=config.target_state,
            fuzzing_mode=config.fuzzing_mode,
            mutable_fields=config.mutable_fields,
            field_mutation_config=config.field_mutation_config,
        )

        self.sessions[session_id] = session
        if behavior_processor.has_behaviors():
            self.behavior_processors[session_id] = behavior_processor

        if protocol.response_handlers:
            planner = ResponsePlanner(
                resolved_data_model,
                resolved_response_model,
                protocol.response_handlers,
            )
            self.response_planners[session_id] = planner
            self.followup_queues.setdefault(session_id, deque())

        # Save initial session state to disk
        await self._checkpoint_session(session)

        logger.info("session_created", session_id=session_id, protocol=config.protocol)
        return session

    async def start_session(self, session_id: str) -> bool:
        """Start a fuzzing session"""
        session = self.sessions.get(session_id)
        if not session:
            logger.error("session_not_found", session_id=session_id)
            return False

        # Check concurrent session limit (configurable via FUZZER_MAX_CONCURRENT_SESSIONS)
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
                f"Stop a session first, or increase FUZZER_MAX_CONCURRENT_SESSIONS (current: {settings.max_concurrent_sessions}). "
                f"Note: Multiple concurrent sessions require more CPU/RAM resources."
            )
            session.error_message = error_msg
            logger.warning(
                "concurrent_session_limit_reached",
                session_id=session_id,
                running_count=len(running_sessions),
                limit=settings.max_concurrent_sessions,
                running_sessions=[s.id for s in running_sessions]
            )
            return False

        if session.status == FuzzSessionStatus.RUNNING:
            logger.warning("session_already_running", session_id=session_id)
            return False

        if session.execution_mode == ExecutionMode.AGENT and not agent_manager.has_agent_for_target(
            session.target_host,
            session.target_port,
            session.transport,
        ):
            session.error_message = (
                "No live agents registered for target "
                f"{session.target_host}:{session.target_port}"
            )
            session.status = FuzzSessionStatus.FAILED
            await self._checkpoint_session(session)
            logger.error("no_agents_for_session", session_id=session_id)
            return False

        session.status = FuzzSessionStatus.RUNNING
        session.started_at = datetime.utcnow()
        await self._checkpoint_session(session)

        # Start fuzzing task
        task = asyncio.create_task(self._run_fuzzing_loop(session_id))
        self.active_tasks[session_id] = task

        logger.info("session_started", session_id=session_id)
        return True

    async def stop_session(self, session_id: str) -> bool:
        """Stop a fuzzing session"""
        session = self.sessions.get(session_id)
        if not session:
            return False

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

        await agent_manager.clear_session(session_id)
        self._discard_pending_tests(session_id)
        self.behavior_processors.pop(session_id, None)
        stateful_session = self.stateful_sessions.get(session_id)
        if session and stateful_session:
            session.coverage_snapshot = stateful_session.get_coverage_stats()
        self.stateful_sessions.pop(session_id, None)  # Clean up stateful session
        self.response_planners.pop(session_id, None)
        self.followup_queues.pop(session_id, None)
        self.session_data_models.pop(session_id, None)
        self.session_response_models.pop(session_id, None)
        self.history_store.reset_session(session_id)

        logger.info("session_stopped", session_id=session_id)
        return True

    async def _initialize_fuzzing_context(
        self, session: FuzzSession, session_id: str
    ) -> tuple[List[bytes], MutationEngine, Optional[StatefulFuzzingSession], Dict]:
        """
        Initialize fuzzing context for a session.

        Returns:
            Tuple of (seeds, mutation_engine, stateful_session, data_model)
        """
        # Load protocol for structure-aware mutations
        protocol = None
        try:
            protocol = plugin_manager.load_plugin(session.protocol)
        except Exception as e:
            logger.warning("failed_to_load_protocol_for_mutations", error=str(e))
            raise PluginError(f"Failed to load protocol '{session.protocol}': {str(e)}")

        data_model = self.session_data_models.get(session_id)
        if protocol and not data_model:
            data_model = denormalize_data_model_from_json(protocol.data_model)
            self.session_data_models[session_id] = data_model

        # Load seeds
        seeds = [self.corpus_store.get_seed(sid) for sid in session.seed_corpus]
        seeds = [s for s in seeds if s is not None]

        if not seeds:
            raise SessionInitializationError(
                "No seeds available for fuzzing",
                details={"session_id": session_id, "seed_corpus": session.seed_corpus}
            )

        # Initialize mutation engine
        mutation_engine = MutationEngine(
            seeds,
            enabled_mutators=session.enabled_mutators,
            data_model=data_model,
            mutation_mode=session.mutation_mode,
            structure_aware_weight=session.structure_aware_weight
        )

        # Setup stateful fuzzing if applicable
        stateful_session = None
        if protocol and protocol.state_model:
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
                        transition_coverage=session.transition_coverage
                    )
                    logger.info(
                        "stateful_session_restored",
                        session_id=session_id,
                        restored_state=session.current_state,
                        state_coverage_size=len(session.state_coverage) if session.state_coverage else 0,
                        transition_coverage_size=len(session.transition_coverage) if session.transition_coverage else 0
                    )

                # Store for metrics access
                self.stateful_sessions[session_id] = stateful_session
                logger.info(
                    "stateful_fuzzing_enabled",
                    session_id=session_id,
                    initial_state=stateful_session.current_state,
                    num_transitions=len(transitions)
                )

        return seeds, mutation_engine, stateful_session, data_model

    def _select_seed_for_iteration(
        self,
        session: FuzzSession,
        seeds: List[bytes],
        stateful_session: Optional[StatefulFuzzingSession],
        iteration: int
    ) -> bytes:
        """
        Select appropriate seed for current iteration based on fuzzing mode.

        Returns:
            Selected seed bytes
        """
        if not stateful_session:
            # Stateless: round-robin seed selection
            return seeds[iteration % len(seeds)]

        # Stateful: select based on fuzzing mode
        base_seed = self._select_message_for_fuzzing_mode(
            session,
            stateful_session,
            seeds,
            iteration
        )

        if base_seed is None:
            # Fallback to standard stateful selection
            message_type = stateful_session.get_message_type_for_state()

            if message_type is None:
                # Terminal state - reset
                logger.debug("terminal_state_reached", iteration=iteration)
                stateful_session.reset_to_initial_state()
                message_type = stateful_session.get_message_type_for_state()

            # Find seed matching this message type
            base_seed = stateful_session.find_seed_for_message_type(message_type, seeds)

            if base_seed is None:
                # No seed found, use fallback
                logger.warning(
                    "no_seed_for_message_type",
                    message_type=message_type,
                    using_random_seed=True
                )
                base_seed = seeds[iteration % len(seeds)]

        return base_seed

    def _generate_mutated_test_case(
        self,
        session: FuzzSession,
        session_id: str,
        seed: bytes,
        mutation_engine: MutationEngine,
        iteration: int
    ) -> tuple[TestCase, dict]:
        """
        Generate a mutated test case from a seed.

        Returns:
            Tuple of (test_case, mutation_metadata)
        """
        # Mutate the seed
        test_case_data = mutation_engine.generate_test_case(seed)
        mutation_meta = mutation_engine.get_last_metadata()

        # Track field mutations
        if mutation_meta.get("field"):
            field_name = mutation_meta["field"]
            session.field_mutation_counts[field_name] = (
                session.field_mutation_counts.get(field_name, 0) + 1
            )

        # Apply behavior processors
        final_data = self._apply_behaviors(session, test_case_data)

        # Determine seed reference
        seed_reference = (
            session.seed_corpus[iteration % len(session.seed_corpus)]
            if session.seed_corpus
            else None
        )

        test_case = TestCase(
            id=str(uuid.uuid4()),
            session_id=session_id,
            data=final_data,
            seed_id=seed_reference,
            mutation_strategy=mutation_meta.get("strategy"),
            mutators_applied=mutation_meta.get("mutators", []),
        )

        return test_case, mutation_meta

    async def _execute_and_record_test_case(
        self,
        session: FuzzSession,
        session_id: str,
        test_case: TestCase,
        stateful_session: Optional[StatefulFuzzingSession]
    ) -> tuple[TestCaseResult, Optional[bytes]]:
        """
        Execute test case and record results.

        Returns:
            Tuple of (result, response)
        """
        if session.execution_mode == ExecutionMode.AGENT:
            await self._dispatch_to_agent(session, test_case)
            return TestCaseResult.PASS, None  # Agent results handled asynchronously

        # Core execution mode
        # Capture state info before execution
        message_type_for_record = None
        state_at_send_for_record = None
        if stateful_session:
            message_type_for_record = stateful_session.identify_message_type(test_case.data)
            state_at_send_for_record = stateful_session.current_state

        # Execute with timing
        timestamp_sent = datetime.utcnow()
        result, response = await self._execute_test_case(session, test_case)
        timestamp_response = datetime.utcnow()

        # Finalize and record
        await self._finalize_test_case(session, test_case, result, response)

        self._record_execution(
            session,
            test_case,
            timestamp_sent,
            timestamp_response,
            result,
            response,
            message_type=message_type_for_record,
            state_at_send=state_at_send_for_record,
            mutation_strategy=test_case.mutation_strategy,
            mutators_applied=test_case.mutators_applied,
        )

        # Handle response followups
        self._evaluate_response_followups(session_id, response)

        return result, response

    def _update_stateful_fuzzing(
        self,
        session: FuzzSession,
        stateful_session: StatefulFuzzingSession,
        test_data: bytes,
        response: Optional[bytes],
        result: TestCaseResult,
        iteration: int
    ) -> None:
        """
        Update stateful fuzzing state after test execution.
        """
        # Update state based on response
        stateful_session.update_state(
            test_data,
            response,
            result.value if result else "unknown"
        )

        # Sync coverage to session
        session.current_state = stateful_session.current_state
        session.state_coverage = stateful_session.get_state_coverage()
        session.transition_coverage = stateful_session.get_transition_coverage()

        # Periodic reset
        reset_interval = self._get_reset_interval(session)
        if stateful_session.should_reset(iteration, reset_interval=reset_interval):
            logger.debug("periodic_state_reset", iteration=iteration)
            stateful_session.reset_to_initial_state()

    async def _run_fuzzing_loop(self, session_id: str):
        """
        Main fuzzing loop for a session.

        Refactored to use helper methods for better maintainability.
        Supports both stateful and stateless fuzzing.
        """
        session = self.sessions[session_id]
        logger.info(
            "fuzzing_loop_started",
            session_id=session_id,
            execution_mode=session.execution_mode,
        )

        # Initialize fuzzing context
        try:
            seeds, mutation_engine, stateful_session, data_model = await self._initialize_fuzzing_context(
                session, session_id
            )
        except (SessionInitializationError, PluginError) as e:
            logger.error(
                "initialization_failed",
                session_id=session_id,
                error=str(e),
                error_type=type(e).__name__,
                details=getattr(e, 'details', {})
            )
            session.status = FuzzSessionStatus.FAILED
            session.error_message = str(e)
            await self._checkpoint_session(session)
            return

        try:
            # Resume from persisted iteration count if this is a resumed session
            # Otherwise start from 0 for new sessions
            iteration = session.total_tests
            if iteration > 0:
                logger.info(
                    "resuming_from_iteration",
                    session_id=session_id,
                    starting_iteration=iteration
                )

            # Calculate rate limiting parameters
            rate_limit_delay = None
            if session.rate_limit_per_second and session.rate_limit_per_second > 0:
                rate_limit_delay = 1.0 / session.rate_limit_per_second
                logger.info(
                    "rate_limiting_enabled",
                    session_id=session_id,
                    rate_limit=session.rate_limit_per_second,
                    delay_per_test=rate_limit_delay,
                )

            while session.status == FuzzSessionStatus.RUNNING:
                # Record test start time for rate limiting
                loop_start = time.time()

                followup_item = None
                queue = self.followup_queues.get(session_id)
                if queue:
                    try:
                        followup_item = queue.popleft()
                    except IndexError:
                        followup_item = None

                mutation_meta = {"strategy": None, "mutators": []}

                if followup_item:
                    # Handle followup from response planner
                    final_data = self._apply_behaviors(session, followup_item["payload"])
                    test_case = TestCase(
                        id=str(uuid.uuid4()),
                        session_id=session_id,
                        data=final_data,
                        seed_id=None,
                        mutation_strategy="response_followup",
                        mutators_applied=["followup"],
                    )
                    logger.info(
                        "followup_dispatched",
                        session_id=session_id,
                        handler=followup_item.get("handler"),
                    )
                else:
                    # Standard fuzzing flow
                    base_seed = self._select_seed_for_iteration(
                        session, seeds, stateful_session, iteration
                    )
                    test_case, mutation_meta = self._generate_mutated_test_case(
                        session, session_id, base_seed, mutation_engine, iteration
                    )

                # Execute and record test case
                result, response = await self._execute_and_record_test_case(
                    session, session_id, test_case, stateful_session
                )

                # Update stateful fuzzing state if applicable
                if stateful_session and session.execution_mode == ExecutionMode.CORE:
                    self._update_stateful_fuzzing(
                        session,
                        stateful_session,
                        test_case.data,
                        response,
                        result,
                        iteration
                    )

                iteration += 1

                # Periodic checkpoint
                if iteration % settings.checkpoint_frequency == 0:
                    await self._checkpoint_session(session)
                    logger.debug("session_checkpointed", session_id=session_id, iteration=iteration)

                if session.max_iterations and iteration >= session.max_iterations:
                    session.status = FuzzSessionStatus.COMPLETED
                    session.completed_at = datetime.utcnow()
                    await self._checkpoint_session(session)
                    break

                # Apply rate limiting - sleep to maintain desired rate
                if rate_limit_delay:
                    elapsed = time.time() - loop_start
                    if elapsed < rate_limit_delay:
                        await asyncio.sleep(rate_limit_delay - elapsed)
                else:
                    # Small yield to event loop if no rate limiting
                    await asyncio.sleep(0.001)

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
                total_tests=session.total_tests,
                iteration=iteration,
                execution_mode=session.execution_mode.value,
                traceback=error_traceback,
            )
            session.status = FuzzSessionStatus.FAILED
            session.error_message = f"Fuzzing error: {type(e).__name__}: {str(e)}"
            await self._checkpoint_session(session)
        finally:
            if session.execution_mode == ExecutionMode.AGENT:
                await agent_manager.clear_session(session_id)
            self._discard_pending_tests(session_id)
            if stateful_session:
                session.coverage_snapshot = stateful_session.get_coverage_stats()
            # Final checkpoint when fuzzing loop exits
            await self._checkpoint_session(session)

    async def _dispatch_to_agent(self, session: FuzzSession, test_case: TestCase) -> None:
        """Send a test case to the agent queue"""
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
        metrics: Optional[Dict[str, float]] = None,
    ) -> None:
        """Update session statistics and persist findings"""
        metrics = metrics or {}
        session.total_tests += 1
        test_case.result = result

        if result == TestCaseResult.CRASH:
            session.crashes += 1
            crash_report = self.crash_reporter.report(
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

    async def handle_agent_result(self, agent_id: str, payload: AgentTestResult) -> Dict[str, Any]:
        """Persist results coming back from an agent"""
        session = self.sessions.get(payload.session_id)
        if not session:
            await agent_manager.complete_work(payload.test_case_id)
            logger.error("agent_result_unknown_session", session_id=payload.session_id)
            return {"status": "unknown_session"}

        test_case = self.pending_tests.pop(payload.test_case_id, None)
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

        timestamp_response = datetime.utcnow()
        duration_ms = payload.execution_time_ms or 0.0
        timestamp_sent = timestamp_response - timedelta(milliseconds=duration_ms)

        self._record_execution(
            session,
            test_case,
            timestamp_sent,
            timestamp_response,
            payload.result,
            response_bytes,
            mutation_strategy=test_case.mutation_strategy,
            mutators_applied=test_case.mutators_applied,
        )

        self._evaluate_response_followups(payload.session_id, response_bytes)

        await agent_manager.complete_work(payload.test_case_id)

        return {"status": "recorded", "result": payload.result}

    async def execute_one_off(self, request: OneOffTestRequest) -> OneOffTestResult:
        """Run a single test case outside of a session"""
        if request.execution_mode == ExecutionMode.AGENT:
            raise ValueError("Agent-mode one-off execution is not yet supported")

        plugin = plugin_manager.load_plugin(request.protocol)
        session_transport = request.transport or plugin.transport

        session_stub = FuzzSession(
            id=str(uuid.uuid4()),
            protocol=request.protocol,
            target_host=request.target_host,
            target_port=request.target_port,
            transport=session_transport,
            seed_corpus=[],
            enabled_mutators=request.mutators or [],
            timeout_per_test_ms=request.timeout_ms,
        )
        test_case = TestCase(
            id=str(uuid.uuid4()),
            session_id=session_stub.id,
            data=request.payload,
        )
        try:
            processor = build_behavior_processor(denormalize_data_model_from_json(plugin.data_model))
            if processor.has_behaviors():
                session_stub.behavior_state = processor.initialize_state()
                test_case.data = processor.apply(test_case.data, session_stub.behavior_state)
        except Exception as exc:
            logger.warning("one_off_behavior_init_failed", error=str(exc))
        result, response = await self._execute_test_case(session_stub, test_case)

        return OneOffTestResult(
            success=result == TestCaseResult.PASS,
            result=result,
            execution_time_ms=test_case.execution_time_ms or 0.0,
            response=response,
            metadata={"session_id": session_stub.id},
        )

    async def _execute_test_case(
        self, session: FuzzSession, test_case: TestCase
    ) -> tuple[TestCaseResult, Optional[bytes]]:
        """
        Execute a test case against the target by actually sending data
        Uses async socket operations to avoid blocking the event loop
        """
        start_time = time.time()
        response: Optional[bytes] = None

        try:
            if session.transport == TransportProtocol.UDP:
                result, response = await self._execute_udp_test_case(session, test_case)
            else:
                result, response = await self._execute_tcp_test_case(session, test_case)
        except Exception as e:
            logger.error("execution_error", error=str(e), test_case_id=test_case.id)
            result = TestCaseResult.CRASH
            response = None

        test_case.result = result
        test_case.execution_time_ms = (time.time() - start_time) * 1000

        return result, response

    async def _execute_tcp_test_case(
        self, session: FuzzSession, test_case: TestCase
    ) -> tuple[TestCaseResult, Optional[bytes]]:
        reader: Optional[asyncio.StreamReader] = None
        writer: Optional[asyncio.StreamWriter] = None

        try:
            try:
                # Use session-specific timeout (convert ms to seconds)
                timeout_sec = session.timeout_per_test_ms / 1000.0
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(session.target_host, session.target_port),
                    timeout=timeout_sec,
                )
            except (ConnectionRefusedError, OSError) as exc:
                logger.error(
                    "target_connection_refused",
                    host=session.target_host,
                    port=session.target_port,
                    error=str(exc),
                )
                if not session.error_message:
                    error_msg = (
                        f"Connection refused to {session.target_host}:{session.target_port}. "
                        "Target may not be running. If running in containers and targeting localhost, "
                        "use '172.17.0.1' (Docker Linux), 'host.docker.internal' (Docker Mac/Windows), "
                        "or 'host.containers.internal' (Podman 4.1+) instead."
                    )
                    session.error_message = error_msg
                    session.status = FuzzSessionStatus.FAILED
                    await self._checkpoint_session(session)
                    logger.warning(
                        "setting_error_message",
                        session_id=session.id,
                        error_message=error_msg,
                    )
                return TestCaseResult.CRASH, None
            except asyncio.TimeoutError:
                logger.debug(
                    "target_timeout",
                    host=session.target_host,
                    port=session.target_port,
                    phase="connect",
                )
                return TestCaseResult.HANG, None

            try:
                writer.write(test_case.data)
                await writer.drain()
                response = await self._read_response_stream(
                    reader,
                    timeout=timeout_sec,
                    max_bytes=settings.max_response_bytes,
                    session_id=session.id,
                )
                result = self._classify_response(session.protocol, response)
                return result, response
            except asyncio.TimeoutError:
                logger.debug(
                    "target_timeout",
                    host=session.target_host,
                    port=session.target_port,
                    phase="read",
                )
                return TestCaseResult.HANG, None
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception as e:
                    logger.warning(
                        "tcp_writer_close_failed",
                        session_id=session.id,
                        error=str(e),
                        error_type=type(e).__name__
                    )

    async def _execute_udp_test_case(
        self, session: FuzzSession, test_case: TestCase
    ) -> tuple[TestCaseResult, Optional[bytes]]:
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[bytes] = loop.create_future()
        max_bytes = settings.max_response_bytes
        session_id = session.id

        class _UDPClient(asyncio.DatagramProtocol):
            def __init__(self):
                self.transport: Optional[asyncio.transports.DatagramTransport] = None

            def connection_made(self, transport: asyncio.BaseTransport) -> None:
                self.transport = transport  # type: ignore[assignment]
                try:
                    transport.sendto(test_case.data)  # type: ignore[attr-defined]
                except Exception as exc:
                    if not response_future.done():
                        response_future.set_exception(exc)

            def datagram_received(self, data: bytes, addr):
                chunk = data
                if len(chunk) > max_bytes:
                    logger.warning(
                        "response_truncated",
                        limit_bytes=max_bytes,
                        session_id=session_id,
                    )
                    chunk = chunk[:max_bytes]
                if not response_future.done():
                    response_future.set_result(chunk)

            def error_received(self, exc):
                if not response_future.done():
                    response_future.set_exception(exc or ConnectionError("udp_error"))

        transport: Optional[asyncio.transports.DatagramTransport] = None
        try:
            # Use session-specific timeout (convert ms to seconds)
            timeout_sec = session.timeout_per_test_ms / 1000.0
            transport, _ = await loop.create_datagram_endpoint(
                _UDPClient,
                remote_addr=(session.target_host, session.target_port),
            )
            response = await asyncio.wait_for(
                response_future,
                timeout=timeout_sec,
            )
            result = self._classify_response(session.protocol, response)
            return result, response
        except asyncio.TimeoutError:
            logger.debug(
                "target_timeout",
                host=session.target_host,
                port=session.target_port,
                phase="udp",
            )
            return TestCaseResult.HANG, None
        except (ConnectionRefusedError, OSError) as exc:
            logger.error(
                "udp_target_unreachable",
                host=session.target_host,
                port=session.target_port,
                error=str(exc),
            )
            if not session.error_message:
                error_msg = (
                    f"Unable to send UDP datagram to {session.target_host}:{session.target_port}. "
                    "Target may not be listening or reachable."
                )
                session.error_message = error_msg
                session.status = FuzzSessionStatus.FAILED
                await self._checkpoint_session(session)
                logger.warning(
                    "setting_error_message",
                    session_id=session.id,
                    error_message=error_msg,
                )
            return TestCaseResult.CRASH, None
        finally:
            if transport:
                try:
                    transport.close()
                except Exception as e:
                    logger.warning(
                        "udp_transport_close_failed",
                        session_id=session.id,
                        error=str(e),
                        error_type=type(e).__name__
                    )

    def _classify_response(self, protocol: str, response: bytes) -> TestCaseResult:
        validator = plugin_manager.get_validator(protocol)
        if not validator:
            return TestCaseResult.PASS
        try:
            is_valid = validator(response)
            return TestCaseResult.PASS if is_valid else TestCaseResult.LOGICAL_FAILURE
        except Exception as exc:
            logger.warning("validator_exception", error=str(exc))
            return TestCaseResult.LOGICAL_FAILURE

    async def _read_response_stream(
        self,
        reader: asyncio.StreamReader,
        timeout: float,
        max_bytes: int,
        session_id: str,
    ) -> bytes:
        """Read up to max_bytes from reader, respecting per-chunk timeout."""
        chunks: List[bytes] = []
        total = 0

        while total < max_bytes:
            read_size = min(settings.tcp_buffer_size, max_bytes - total)
            try:
                chunk = await asyncio.wait_for(reader.read(read_size), timeout=timeout)
            except asyncio.TimeoutError:
                if not chunks:
                    raise
                logger.debug("response_read_timeout_partial", received=total)
                break

            if not chunk:
                break

            chunks.append(chunk)
            total += len(chunk)

            if total >= max_bytes:
                logger.warning(
                    "response_truncated",
                    limit_bytes=max_bytes,
                    session_id=session_id,
                )
                break

        return b"".join(chunks)

    def _record_execution(
        self,
        session: FuzzSession,
        test_case: TestCase,
        timestamp_sent: datetime,
        timestamp_response: datetime,
        result: TestCaseResult,
        response: Optional[bytes],
        message_type: Optional[str] = None,
        state_at_send: Optional[str] = None,
        mutation_strategy: Optional[str] = None,
        mutators_applied: Optional[List[str]] = None,
    ) -> TestCaseExecutionRecord:
        """Record a test case execution for correlation.

        Note: mutation_strategy and mutators_applied are accepted for backward
        compatibility but not passed to record() - they're extracted from test_case.
        """
        try:
            record = self.history_store.record(
                session,
                test_case,
                timestamp_sent,
                timestamp_response,
                result,
                response,
                message_type=message_type,
                state_at_send=state_at_send,
            )
            logger.debug(
                "execution_recorded",
                session_id=session.id,
                test_case_id=test_case.id,
                result=result.value,
                mutation_strategy=test_case.mutation_strategy,
                mutators_applied=test_case.mutators_applied,
            )
            return record
        except Exception as exc:
            logger.error(
                "execution_record_failed",
                session_id=session.id,
                test_case_id=test_case.id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise

    def _resolve_mutators(self, config: FuzzConfig) -> List[str]:
        """Translate config into concrete mutator names"""
        if config.enabled_mutators:
            return config.enabled_mutators

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

    def _evaluate_response_followups(self, session_id: str, response: Optional[bytes]) -> None:
        if not response:
            return

        planner = self.response_planners.get(session_id)
        if not planner:
            return

        followups = planner.plan(response)
        if not followups:
            return

        queue = self.followup_queues.setdefault(session_id, deque())
        for followup in followups:
            queue.append(followup)
            logger.info(
                "response_followup_queued",
                session_id=session_id,
                handler=followup.get("handler"),
            )

    def _discard_pending_tests(self, session_id: str) -> None:
        """Remove pending tests for a session"""
        stale = [tc_id for tc_id, tc in self.pending_tests.items() if tc.session_id == session_id]
        for tc_id in stale:
            self.pending_tests.pop(tc_id, None)

    def _apply_behaviors(self, session: FuzzSession, data: bytes) -> bytes:
        processor = self.behavior_processors.get(session.id)
        if not processor:
            return data
        state = session.behavior_state or processor.initialize_state()
        session.behavior_state = state
        return processor.apply(data, state)

    def get_session(self, session_id: str) -> Optional[FuzzSession]:
        """Get session by ID"""
        return self.sessions.get(session_id)

    def list_sessions(self) -> List[FuzzSession]:
        """List all sessions"""
        return list(self.sessions.values())

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and clean up resources"""
        session = self.sessions.get(session_id)
        if not session:
            return False

        # Stop the session if it's running
        if session.status == FuzzSessionStatus.RUNNING:
            await self.stop_session(session_id)

        # Remove from sessions dict
        del self.sessions[session_id]

        # Remove from persistence database
        self.session_store.delete_session(session_id)

        # Clean up runtime helpers
        self.behavior_processors.pop(session_id, None)
        self.response_planners.pop(session_id, None)
        self.followup_queues.pop(session_id, None)
        self.stateful_sessions.pop(session_id, None)

        logger.info("session_deleted", session_id=session_id)
        return True

    def get_session_stats(self, session_id: str) -> Optional[Dict]:
        """Get session statistics"""
        session = self.sessions.get(session_id)
        if not session:
            return None

        findings = self.corpus_store.list_findings(session_id)

        stats = {
            "session_id": session_id,
            "status": session.status.value,  # Convert enum to string
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
        stateful_session = self.stateful_sessions.get(session_id)
        if stateful_session:
            stats["state_coverage"] = stateful_session.get_coverage_stats()

        return stats

    def get_state_coverage(self, session_id: str) -> Optional[Dict]:
        """
        Get state coverage for a stateful fuzzing session.

        Args:
            session_id: Session ID

        Returns:
            State coverage stats or None if not stateful
        """
        session = self.sessions.get(session_id)
        stateful_session = self.stateful_sessions.get(session_id)
        if stateful_session:
            coverage = stateful_session.get_coverage_stats()
            if session:
                session.coverage_snapshot = coverage
            return coverage

        if session and session.coverage_snapshot:
            return session.coverage_snapshot

        return None

    def get_execution_history(
        self,
        session_id: str,
        limit: int = None,
        offset: int = 0,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None
    ) -> List[TestCaseExecutionRecord]:
        """Get execution history for a session"""
        if limit is None:
            limit = settings.default_history_limit
        return self.history_store.list(
            session_id,
            limit=limit,
            offset=offset,
            since=since,
            until=until,
        )

    def find_execution_by_sequence(self, session_id: str, sequence_number: int) -> Optional[TestCaseExecutionRecord]:
        """Find execution by sequence number"""

        return self.history_store.find_by_sequence(session_id, sequence_number)

    def find_execution_at_time(self, session_id: str, timestamp: datetime) -> Optional[TestCaseExecutionRecord]:
        """Find execution that was running at given timestamp"""

        return self.history_store.find_at_time(session_id, timestamp)

    def _get_reset_interval(self, session: FuzzSession) -> int:
        """
        Determine state reset interval based on fuzzing mode.

        Args:
            session: Fuzzing session

        Returns:
            Reset interval in iterations
        """
        if session.fuzzing_mode == "breadth_first":
            # Reset frequently to explore all states evenly
            return settings.stateful_reset_interval_bfs
        elif session.fuzzing_mode == "depth_first":
            # Reset rarely to follow deep paths
            return settings.stateful_reset_interval_dfs
        elif session.fuzzing_mode == "targeted" and session.target_state:
            # Reset rarely when targeting specific state (stay in target state)
            return settings.stateful_reset_interval_targeted
        else:
            # Default: random mode
            return settings.stateful_reset_interval_random

    def _should_navigate_to_target_state(
        self,
        session: FuzzSession,
        stateful_session: Any,
        iteration: int
    ) -> bool:
        """
        Determine if we should navigate to target state.

        Used in targeted mode to reach the target state before fuzzing.

        Args:
            session: Fuzzing session
            stateful_session: StatefulFuzzingSession instance
            iteration: Current iteration

        Returns:
            True if should navigate to target
        """
        if session.fuzzing_mode != "targeted" or not session.target_state:
            return False

        # Already at target state - no need to navigate
        if stateful_session.current_state == session.target_state:
            return False

        # Not at target, need to navigate
        return True

    def _select_message_for_fuzzing_mode(
        self,
        session: FuzzSession,
        stateful_session: Any,
        seeds: List[bytes],
        iteration: int
    ) -> Optional[bytes]:
        """
        Select appropriate message based on fuzzing mode and targeting.

        Args:
            session: Fuzzing session
            stateful_session: StatefulFuzzingSession instance
            seeds: Available seed messages
            iteration: Current iteration

        Returns:
            Selected seed message, or None for fallback
        """
        if session.fuzzing_mode == "breadth_first":
            # Select messages that lead to least-visited states
            valid_transitions = stateful_session.get_valid_transitions()
            if not valid_transitions:
                return None

            state_coverage = stateful_session.get_state_coverage()

            # Find transition leading to least-visited state
            best_transition = min(
                valid_transitions,
                key=lambda t: state_coverage.get(t.get("to", ""), 0)
            )

            message_type = best_transition.get("message_type")
            if message_type:
                return stateful_session.find_seed_for_message_type(message_type, seeds)

        elif session.fuzzing_mode == "depth_first":
            # Always follow the first transition (deep paths)
            message_type = stateful_session.get_message_type_for_state()
            if message_type:
                return stateful_session.find_seed_for_message_type(message_type, seeds)

        elif session.fuzzing_mode == "targeted":
            # Navigate to target state, then fuzz messages in that state
            if self._should_navigate_to_target_state(session, stateful_session, iteration):
                # Navigate: select message that moves toward target
                message_type = self._select_message_toward_target(
                    session.target_state,
                    stateful_session
                )
                if message_type:
                    return stateful_session.find_seed_for_message_type(message_type, seeds)
            else:
                # Already at target - select any valid message for target state
                message_type = stateful_session.get_message_type_for_state()
                if message_type:
                    return stateful_session.find_seed_for_message_type(message_type, seeds)

        # Default: use standard stateful selection
        return None

    def _select_message_toward_target(
        self,
        target_state: str,
        stateful_session: Any
    ) -> Optional[str]:
        """
        Select message type that moves toward target state.

        Simple BFS to find path to target state and return first step.

        Args:
            target_state: Desired target state
            stateful_session: StatefulFuzzingSession instance

        Returns:
            Message type to send, or None if unreachable
        """
        from collections import deque

        current = stateful_session.current_state
        if current == target_state:
            # Already there
            return stateful_session.get_message_type_for_state()

        # BFS to find path
        queue = deque([(current, [])])
        visited = {current}

        state_model = stateful_session.state_model
        transitions = state_model.get("transitions", [])

        while queue:
            state, path = queue.popleft()

            # Get valid transitions from this state
            for transition in transitions:
                if transition.get("from") != state:
                    continue

                to_state = transition.get("to")
                message_type = transition.get("message_type")

                if to_state == target_state:
                    # Found path! Return first message type in path
                    if path:
                        return path[0]
                    else:
                        return message_type

                if to_state not in visited:
                    visited.add(to_state)
                    new_path = path + [message_type] if path else [message_type]
                    queue.append((to_state, new_path))

        # No path found
        logger.warning(
            "no_path_to_target_state",
            current=current,
            target=target_state
        )
        return None

    async def replay_executions(
        self,
        session_id: str,
        sequence_numbers: List[int],
        delay_ms: int = 0
    ) -> List[TestCaseExecutionRecord]:
        """Replay test cases by sequence number"""

        session = self.sessions.get(session_id)
        if not session:
            return []

        results = []

        for seq_num in sequence_numbers:
            # Find original execution
            original = self.find_execution_by_sequence(session_id, seq_num)
            if not original:
                continue

            # Decode payload
            payload = base64.b64decode(original.raw_payload_b64)

            # Create new test case
            test_case = TestCase(
                id=str(uuid.uuid4()),
                session_id=session_id,
                data=payload,
                seed_id=None,  # Replay, not from seed
                mutation_strategy=original.mutation_strategy,
                mutators_applied=list(original.mutators_applied or []),
            )

            # Execute
            timestamp_sent = datetime.utcnow()
            result, response = await self._execute_test_case(session, test_case)
            timestamp_response = datetime.utcnow()

            # Record the replay
            replay_record = self._record_execution(
                session,
                test_case,
                timestamp_sent,
                timestamp_response,
                result,
                response,
                message_type=original.message_type,
                state_at_send=original.state_at_send,
                mutation_strategy=test_case.mutation_strategy,
                mutators_applied=test_case.mutators_applied,
            )

            results.append(replay_record)

            # Apply delay if specified
            if delay_ms > 0 and seq_num != sequence_numbers[-1]:
                await asyncio.sleep(delay_ms / 1000.0)

        return results


# Global orchestrator instance
orchestrator = FuzzOrchestrator()
