"""Crash reporting utilities."""
from typing import Optional

import structlog

from core.corpus.store import CorpusStore
from core.models import CrashReport, FuzzSession, TestCase, TestCaseResult

logger = structlog.get_logger(__name__)


class CrashReporter:
    """Persists crash findings via the corpus store."""

    def __init__(self, corpus_store: CorpusStore):
        self._corpus_store = corpus_store

    def report(
        self,
        session: FuzzSession,
        test_case: TestCase,
        cpu_usage: Optional[float] = None,
        memory_usage: Optional[float] = None,
        response: Optional[bytes] = None,
    ) -> CrashReport:
        crash_report = CrashReport(
            id=test_case.id,
            session_id=session.id,
            test_case_id=test_case.id,
            result_type=test_case.result or TestCaseResult.CRASH,
            reproducer_data=test_case.data,
            response_data=response,
            response_preview=response[:64].hex() if response else None,
            severity="medium",
            cpu_usage=cpu_usage,
            memory_usage_mb=memory_usage,
        )
        try:
            self._corpus_store.save_finding(crash_report, test_case.data)
            logger.info(
                "crash_reported",
                session_id=session.id,
                test_case_id=test_case.id,
                result_type=str(crash_report.result_type),
                severity=crash_report.severity,
                data_size=len(test_case.data),
                has_response=response is not None,
            )
        except Exception:
            logger.error(
                "crash_save_failed",
                session_id=session.id,
                test_case_id=test_case.id,
                exc_info=True,
            )
        return crash_report
