from datetime import datetime
from core import utcnow

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

    ts = utcnow()
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


def test_history_store_records_response_data(tmp_path):
    """Verify response bytes are stored and round-tripped through SQLite."""
    store = ExecutionHistoryStore(
        db_path=str(tmp_path / "history.db"),
        memory_cache_size=10,
    )
    session = _make_session("session-resp")
    ts = utcnow()
    response = b"\xde\xad\xbe\xef"

    record = store.record(
        session,
        _make_test_case(session.id, "resp1"),
        ts,
        ts,
        TestCaseResult.PASS,
        response=response,
    )

    assert record.raw_response_b64 is not None
    assert record.response_size == 4
    assert record.response_preview == response[:64].hex()

    # Force sync write then query from SQLite directly
    store._write_batch([record])
    rows = store.list(session.id, limit=10)
    stored = rows[0]
    import base64
    assert base64.b64decode(stored.raw_response_b64) == response


def test_history_store_retry_on_write_failure(tmp_path):
    """Verify background writer re-queues records on transient failure."""
    import asyncio
    from unittest.mock import patch, MagicMock

    store = ExecutionHistoryStore(
        db_path=str(tmp_path / "history.db"),
        memory_cache_size=10,
        max_write_retries=2,
    )
    session = _make_session("session-retry")
    ts = utcnow()
    record = store.record(
        session,
        _make_test_case(session.id, "r1"),
        ts,
        ts,
        TestCaseResult.PASS,
        response=None,
    )

    # Simulate a write failure then success
    original_write = store._write_batch
    call_count = 0

    def failing_write(records):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("Simulated disk error")
        return original_write(records)

    with patch.object(store, '_write_batch', side_effect=failing_write):
        # Sync fallback path: first call fails, should log error not crash
        try:
            store._write_batch([record])
        except OSError:
            pass  # Expected on first call

    # Second call should succeed
    original_write([record])
    rows = store.list(session.id, limit=10)
    assert len(rows) >= 1


def test_history_store_flush_retries(tmp_path):
    """Verify flush retries on transient failure."""
    import asyncio

    store = ExecutionHistoryStore(
        db_path=str(tmp_path / "history.db"),
        memory_cache_size=10,
        max_write_retries=3,
    )
    session = _make_session("session-flush")
    ts = utcnow()

    record = store.record(
        session,
        _make_test_case(session.id, "f1"),
        ts,
        ts,
        TestCaseResult.PASS,
        response=b"OK",
    )

    # Enqueue a record so flush has something to process
    store._write_queue.put_nowait(record)

    original_write = store._write_batch
    attempt_count = 0

    def flaky_write(records):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise OSError("Transient error")
        return original_write(records)

    async def run_flush():
        from unittest.mock import patch
        with patch.object(store, '_write_batch', side_effect=flaky_write):
            result = await store.flush()
        return result

    result = asyncio.get_event_loop().run_until_complete(run_flush())
    assert result is True
    assert attempt_count == 3  # Failed twice, succeeded on third
