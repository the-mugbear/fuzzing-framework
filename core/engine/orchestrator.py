"""
Fuzzing orchestrator - coordinates the fuzzing campaign
"""
import asyncio
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import structlog

from core.config import settings
from core.corpus.store import CorpusStore
from core.engine.mutators import MutationEngine
from core.models import (
    CrashReport,
    FuzzConfig,
    FuzzSession,
    FuzzSessionStatus,
    TestCase,
    TestCaseResult,
)
from core.plugins.loader import plugin_manager

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

        # Initialize seed corpus from plugin
        seed_corpus = []
        if "seeds" in protocol.data_model:
            for seed in protocol.data_model["seeds"]:
                seed_id = self.corpus_store.add_seed(
                    seed, metadata={"protocol": config.protocol, "source": "plugin"}
                )
                seed_corpus.append(seed_id)

        session = FuzzSession(
            id=session_id,
            protocol=config.protocol,
            target_host=config.target_host,
            target_port=config.target_port,
            seed_corpus=seed_corpus,
            status=FuzzSessionStatus.IDLE,
        )

        self.sessions[session_id] = session
        logger.info("session_created", session_id=session_id, protocol=config.protocol)
        return session

    async def start_session(self, session_id: str) -> bool:
        """Start a fuzzing session"""
        session = self.sessions.get(session_id)
        if not session:
            logger.error("session_not_found", session_id=session_id)
            return False

        if session.status == FuzzSessionStatus.RUNNING:
            logger.warning("session_already_running", session_id=session_id)
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

        logger.info("session_stopped", session_id=session_id)
        return True

    async def _run_fuzzing_loop(self, session_id: str):
        """
        Main fuzzing loop for a session

        This is a simplified version for MVP - just generates mutations
        and simulates sending them. Full version will integrate with agents.
        """
        session = self.sessions[session_id]
        logger.info("fuzzing_loop_started", session_id=session_id)

        # Load seeds
        seeds = [self.corpus_store.get_seed(sid) for sid in session.seed_corpus]
        seeds = [s for s in seeds if s is not None]

        if not seeds:
            logger.error("no_seeds_available", session_id=session_id)
            session.status = FuzzSessionStatus.FAILED
            return

        # Initialize mutation engine
        mutation_engine = MutationEngine(seeds)

        try:
            iteration = 0
            while session.status == FuzzSessionStatus.RUNNING:
                # Generate test case
                base_seed = seeds[iteration % len(seeds)]
                test_case_data = mutation_engine.generate_test_case(base_seed)

                # Create test case record
                test_case = TestCase(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    data=test_case_data,
                    seed_id=session.seed_corpus[iteration % len(session.seed_corpus)],
                )

                # Execute test case (MVP: simulated, will integrate with agent)
                result = await self._execute_test_case(session, test_case)

                # Update statistics
                session.total_tests += 1

                if result == TestCaseResult.CRASH:
                    session.crashes += 1
                    await self._handle_crash(session, test_case)
                elif result == TestCaseResult.HANG:
                    session.hangs += 1
                elif result in (TestCaseResult.ANOMALY, TestCaseResult.LOGICAL_FAILURE):
                    session.anomalies += 1

                iteration += 1

                # Small delay to prevent overwhelming the target
                await asyncio.sleep(0.001)

        except asyncio.CancelledError:
            logger.info("fuzzing_loop_cancelled", session_id=session_id)
        except Exception as e:
            logger.error("fuzzing_loop_error", session_id=session_id, error=str(e))
            session.status = FuzzSessionStatus.FAILED
            session.error_message = f"Fuzzing error: {str(e)}"

    async def _execute_test_case(self, session: FuzzSession, test_case: TestCase) -> TestCaseResult:
        """
        Execute a test case against the target by actually sending data
        """
        import socket
        start_time = time.time()

        try:
            # Connect to target
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(settings.mutation_timeout_sec)

            try:
                sock.connect((session.target_host, session.target_port))
            except ConnectionRefusedError:
                logger.error("target_connection_refused",
                           host=session.target_host,
                           port=session.target_port)
                # Set session error message for the first connection failure
                # Note: total_tests hasn't been incremented yet, so check <= 0
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
                return TestCaseResult.CRASH

            # Send test data
            sock.sendall(test_case.data)

            # Try to receive response (with timeout)
            try:
                response = sock.recv(4096)

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

            except socket.timeout:
                logger.debug("target_timeout", host=session.target_host, port=session.target_port)
                result = TestCaseResult.HANG

            sock.close()

        except socket.timeout:
            result = TestCaseResult.HANG
        except Exception as e:
            logger.error("execution_error", error=str(e), test_case_id=test_case.id)
            result = TestCaseResult.CRASH

        test_case.result = result
        test_case.execution_time_ms = (time.time() - start_time) * 1000

        return result

    async def _handle_crash(self, session: FuzzSession, test_case: TestCase):
        """Handle a crash finding"""
        crash_report = CrashReport(
            id=str(uuid.uuid4()),
            session_id=session.id,
            test_case_id=test_case.id,
            result_type=test_case.result,
            reproducer_data=test_case.data,
            severity="medium",  # Will be triaged properly in full version
        )

        # Save to corpus store
        self.corpus_store.save_finding(crash_report, test_case.data)

        logger.warning(
            "crash_detected",
            session_id=session.id,
            finding_id=crash_report.id,
            test_case_id=test_case.id,
        )

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

        return {
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


# Global orchestrator instance
orchestrator = FuzzOrchestrator()
