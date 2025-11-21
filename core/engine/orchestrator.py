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
        logger.info("session_created", session_id=session_id, protocol=config.protocol)
        return session

    async def start_session(self, session_id: str) -> bool:
        """Start a fuzzing session"""
        session = self.sessions.get(session_id)
        if not session:
            logger.error("session_not_found", session_id=session_id)
            return False

        # Check if another session is already running
        running_sessions = [
            s for s in self.sessions.values()
            if s.status == FuzzSessionStatus.RUNNING and s.id != session_id
        ]
        if running_sessions:
            running_session_ids = ", ".join([s.id[:8] for s in running_sessions])
            error_msg = (
                f"Cannot start session: another session is already running ({running_session_ids}...). "
                f"Only one session can run at a time. Please stop the running session first."
            )
            session.error_message = error_msg
            logger.warning(
                "cannot_start_multiple_sessions",
                session_id=session_id,
                running_sessions=running_session_ids
            )
            return False

        if session.status == FuzzSessionStatus.RUNNING:
            logger.warning("session_already_running", session_id=session_id)
            return False

        if session.execution_mode == ExecutionMode.AGENT and not agent_manager.has_agent_for_target(
            session.target_host, session.target_port
        ):
            session.error_message = (
                "No live agents registered for target "
                f"{session.target_host}:{session.target_port}"
            )
            session.status = FuzzSessionStatus.FAILED
            logger.error("no_agents_for_session", session_id=session_id)
            return False

        session.status = FuzzSessionStatus.RUNNING
        session.started_at = datetime.utcnow()

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

    async def _run_fuzzing_loop(self, session_id: str):
        """
        Main fuzzing loop for a session

        Session executes either locally or via agent queues.
        Supports both stateful and stateless fuzzing.
        """
        session = self.sessions[session_id]
        logger.info(
            "fuzzing_loop_started",
            session_id=session_id,
            execution_mode=session.execution_mode,
        )

        # Load protocol for structure-aware mutations
        protocol = None
        try:
            protocol = plugin_manager.load_plugin(session.protocol)
        except Exception as e:
            logger.warning("failed_to_load_protocol_for_mutations", error=str(e))

        data_model = self.session_data_models.get(session_id)
        if protocol and not data_model:
            data_model = denormalize_data_model_from_json(protocol.data_model)
            self.session_data_models[session_id] = data_model

        # Load seeds
        seeds = [self.corpus_store.get_seed(sid) for sid in session.seed_corpus]
        seeds = [s for s in seeds if s is not None]

        if not seeds:
            logger.error("no_seeds_available", session_id=session_id)
            session.status = FuzzSessionStatus.FAILED
            return

        # Initialize mutation engine with selected mutators and protocol data_model
        mutation_engine = MutationEngine(
            seeds,
            enabled_mutators=session.enabled_mutators,
            data_model=data_model,
            mutation_mode=session.mutation_mode,
            structure_aware_weight=session.structure_aware_weight
        )

        # Check if protocol has state model for stateful fuzzing
        stateful_session = None
        use_stateful_fuzzing = False

        if protocol and protocol.state_model:
            transitions = protocol.state_model.get("transitions", [])
            if transitions:
                use_stateful_fuzzing = True
                response_model = None
                if protocol.response_model:
                    response_model = denormalize_data_model_from_json(protocol.response_model)

                stateful_session = StatefulFuzzingSession(
                    protocol.state_model,
                    data_model or denormalize_data_model_from_json(protocol.data_model),
                    response_model=response_model,
                    progression_weight=0.8  # 80% follow happy path
                )
                # Store stateful session for metrics access
                self.stateful_sessions[session_id] = stateful_session
                logger.info(
                    "stateful_fuzzing_enabled",
                    session_id=session_id,
                    initial_state=stateful_session.current_state,
                    num_transitions=len(transitions)
                )

        try:
            iteration = 0

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
                    final_data = self._apply_behaviors(session, followup_item["payload"])
                    seed_reference = None
                    mutation_meta = {"strategy": "response_followup", "mutators": ["followup"]}
                    logger.info(
                        "followup_dispatched",
                        session_id=session_id,
                        handler=followup_item.get("handler"),
                    )
                else:
                    # Generate test case based on fuzzing mode
                    if use_stateful_fuzzing:
                        # Stateful fuzzing: select message for current state
                        message_type = stateful_session.get_message_type_for_state()

                        if message_type is None:
                            # Terminal state - reset
                            logger.debug("terminal_state_reached", iteration=iteration)
                            stateful_session.reset_to_initial_state()
                            message_type = stateful_session.get_message_type_for_state()

                        # Find seed matching this message type
                        base_seed = stateful_session.find_seed_for_message_type(message_type, seeds)

                        if base_seed is None:
                            # No seed found for this message type, use fallback
                            logger.warning(
                                "no_seed_for_message_type",
                                message_type=message_type,
                                using_random_seed=True
                            )
                            base_seed = seeds[iteration % len(seeds)]
                    else:
                        # Stateless fuzzing: random seed selection (existing behavior)
                        base_seed = seeds[iteration % len(seeds)]

                    # Mutate the selected seed
                    test_case_data = mutation_engine.generate_test_case(base_seed)
                    mutation_meta = mutation_engine.get_last_metadata()
                    final_data = self._apply_behaviors(session, test_case_data)
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

                # Execute test case
                if session.execution_mode == ExecutionMode.CORE:
                    # Capture state info before execution
                    message_type_for_record = None
                    state_at_send_for_record = None
                    if use_stateful_fuzzing:
                        message_type_for_record = stateful_session.identify_message_type(final_data)
                        state_at_send_for_record = stateful_session.current_state

                    # Record timestamps for correlation
                    timestamp_sent = datetime.utcnow()
                    result, response = await self._execute_test_case(session, test_case)
                    timestamp_response = datetime.utcnow()

                    await self._finalize_test_case(session, test_case, result)

                    # Record execution for correlation/replay
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

                    self._evaluate_response_followups(session_id, response)

                    # Update state if using stateful fuzzing
                    if use_stateful_fuzzing:
                        stateful_session.update_state(
                            final_data,
                            response,
                            result.value if result else "unknown"
                        )

                        # Periodically reset state to explore different paths
                        if stateful_session.should_reset(iteration, reset_interval=100):
                            logger.debug("periodic_state_reset", iteration=iteration)
                            stateful_session.reset_to_initial_state()
                else:
                    await self._dispatch_to_agent(session, test_case)

                iteration += 1

                if session.max_iterations and iteration >= session.max_iterations:
                    session.status = FuzzSessionStatus.COMPLETED
                    session.completed_at = datetime.utcnow()
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
            logger.error("fuzzing_loop_error", session_id=session_id, error=str(e))
            session.status = FuzzSessionStatus.FAILED
            session.error_message = f"Fuzzing error: {str(e)}"
        finally:
            if session.execution_mode == ExecutionMode.AGENT:
                await agent_manager.clear_session(session_id)
            self._discard_pending_tests(session_id)
            if stateful_session:
                session.coverage_snapshot = stateful_session.get_coverage_stats()

    async def _dispatch_to_agent(self, session: FuzzSession, test_case: TestCase) -> None:
        """Send a test case to the agent queue"""
        work = AgentWorkItem(
            session_id=session.id,
            test_case_id=test_case.id,
            protocol=session.protocol,
            target_host=session.target_host,
            target_port=session.target_port,
            data=test_case.data,
            timeout_ms=session.timeout_per_test_ms,
        )
        self.pending_tests[test_case.id] = test_case
        await agent_manager.enqueue_test_case(session.target_host, session.target_port, work)

    async def _finalize_test_case(
        self,
        session: FuzzSession,
        test_case: TestCase,
        result: TestCaseResult,
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

        test_case.execution_time_ms = payload.execution_time_ms
        await self._finalize_test_case(
            session,
            test_case,
            payload.result,
            metrics={
                "cpu_usage": payload.cpu_usage or 0.0,
                "memory_usage_mb": payload.memory_usage_mb or 0.0,
            },
        )

        timestamp_response = datetime.utcnow()
        duration_ms = payload.execution_time_ms or 0.0
        timestamp_sent = timestamp_response - timedelta(milliseconds=duration_ms)
        response_bytes = payload.response if payload.response else None

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

        session_stub = FuzzSession(
            id=str(uuid.uuid4()),
            protocol=request.protocol,
            target_host=request.target_host,
            target_port=request.target_port,
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
            plugin = plugin_manager.load_plugin(request.protocol)
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
        response = None

        try:
            # Connect to target using async sockets
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(session.target_host, session.target_port),
                    timeout=settings.mutation_timeout_sec
                )
            except (ConnectionRefusedError, OSError) as e:
                logger.error("target_connection_refused",
                           host=session.target_host,
                           port=session.target_port,
                           error=str(e))
                # Set session error message for the first connection failure
                if not session.error_message:
                    error_msg = (
                        f"Connection refused to {session.target_host}:{session.target_port}. "
                        f"Target may not be running. If running in Docker and targeting localhost, "
                        f"use '172.17.0.1' (Linux) or 'host.docker.internal' (Mac/Windows) instead."
                    )
                    session.error_message = error_msg
                    session.status = FuzzSessionStatus.FAILED
                    logger.warning("setting_error_message",
                                 session_id=session.id,
                                 error_message=error_msg)
                test_case.result = TestCaseResult.CRASH
                test_case.execution_time_ms = (time.time() - start_time) * 1000
                return TestCaseResult.CRASH, None

            try:
                # Send test data
                writer.write(test_case.data)
                await writer.drain()

                # Try to receive response (with timeout)
                try:
                    response = await self._read_response_stream(
                        reader,
                        timeout=settings.mutation_timeout_sec,
                        max_bytes=settings.max_response_bytes,
                        session_id=session.id,
                    )

                    # Check if response is valid using protocol validator
                    validator = plugin_manager.get_validator(session.protocol)
                    if validator:
                        try:
                            is_valid = validator(response)
                            if not is_valid:
                                result = TestCaseResult.LOGICAL_FAILURE
                            else:
                                result = TestCaseResult.PASS
                        except Exception as e:
                            logger.warning("validator_exception", error=str(e))
                            result = TestCaseResult.LOGICAL_FAILURE
                    else:
                        result = TestCaseResult.PASS

                except asyncio.TimeoutError:
                    logger.debug("target_timeout", host=session.target_host, port=session.target_port)
                    result = TestCaseResult.HANG
                    response = None

            finally:
                # Clean up connection
                writer.close()
                await writer.wait_closed()

        except asyncio.TimeoutError:
            result = TestCaseResult.HANG
            response = None
        except Exception as e:
            logger.error("execution_error", error=str(e), test_case_id=test_case.id)
            result = TestCaseResult.CRASH
            response = None

        test_case.result = result
        test_case.execution_time_ms = (time.time() - start_time) * 1000

        return result, response

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
            read_size = min(4096, max_bytes - total)
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
        """Record a test case execution for correlation"""
        return self.history_store.record(
            session,
            test_case,
            timestamp_sent,
            timestamp_response,
            result,
            response,
            message_type=message_type,
            state_at_send=state_at_send,
            mutation_strategy=mutation_strategy,
            mutators_applied=mutators_applied,
        )

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

    def get_session_stats(self, session_id: str) -> Optional[Dict]:
        """Get session statistics"""
        session = self.sessions.get(session_id)
        if not session:
            return None

        findings = self.corpus_store.list_findings(session_id)

        stats = {
            "session_id": session_id,
            "status": session.status,
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
        limit: int = 100,
        offset: int = 0,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None
    ) -> List[TestCaseExecutionRecord]:
        """Get execution history for a session"""
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
