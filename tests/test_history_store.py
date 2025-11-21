from datetime import datetime

from core.engine.history_store import ExecutionHistoryStore
from core.models import ExecutionMode, FuzzSession, FuzzSessionStatus, TestCase, TestCaseResult


def _make_session(session_id: str) -> FuzzSession:
    return FuzzSession(
        id=session_id,
        protocol="simple",
        execution_mode=ExecutionMode.CORE,
        status=FuzzSessionStatus.IDLE,
        target_host="localhost",
        target_port=1234,
    )


def _make_test_case(session_id: str, suffix: str) -> TestCase:
    return TestCase(
        id=f"tc-{suffix}",
        session_id=session_id,
        data=b"\x00\x01",
    )


def test_history_store_sequences_are_monotonic(tmp_path):
    store = ExecutionHistoryStore(
        db_path=str(tmp_path / "history.db"),
        memory_cache_size=10,
    )
    session = _make_session("session-1")

    ts = datetime.utcnow()
    record_one = store.record(
        session,
        _make_test_case(session.id, "one"),
        ts,
        ts,
        TestCaseResult.PASS,
        response=None,
    )

    record_two = store.record(
        session,
        _make_test_case(session.id, "two"),
        ts,
        ts,
        TestCaseResult.PASS,
        response=None,
    )

    assert record_one.sequence_number == 1
    assert record_two.sequence_number == 2
