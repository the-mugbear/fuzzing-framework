"""Crash reporting utilities."""
from typing import Optional

from core.corpus.store import CorpusStore
from core.models import CrashReport, FuzzSession, TestCase, TestCaseResult


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
    ) -> CrashReport:
        crash_report = CrashReport(
            id=test_case.id,
            session_id=session.id,
            test_case_id=test_case.id,
            result_type=test_case.result or TestCaseResult.CRASH,
            reproducer_data=test_case.data,
            severity="medium",
            cpu_usage=cpu_usage,
            memory_usage_mb=memory_usage,
        )
        self._corpus_store.save_finding(crash_report, test_case.data)
        return crash_report
