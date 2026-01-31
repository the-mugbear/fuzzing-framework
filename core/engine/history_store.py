"""Utilities for tracking execution history with SQLite persistence."""
import asyncio
import base64
import hashlib
import json
import sqlite3
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from core.models import FuzzSession, TestCase, TestCaseExecutionRecord, TestCaseResult

logger = structlog.get_logger()


def _json_safe(obj):
    """Convert an object to JSON-safe format, encoding bytes as base64."""
    if obj is None:
        return None
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("utf-8")
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


class ExecutionHistoryStore:
    """SQLite-backed storage for execution records with async batched writes."""

    def __init__(self, db_path: str = "data/correlation.db", memory_cache_size: int = 100):
        self.db_path = db_path
        self.memory_cache_size = memory_cache_size

        # Memory cache for recent tests (fast UI queries)
        self._recent_cache: Dict[str, deque] = {}
        self._sequence_counters: Dict[str, int] = {}

        # Async write queue for batching
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Initialize database
        self._init_database()

        logger.info("history_store_initialized", db_path=db_path, cache_size=memory_cache_size)

    def _init_database(self):
        """Create database schema with indexes if it doesn't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    session_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    test_case_id TEXT NOT NULL,
                    timestamp_sent REAL NOT NULL,
                    timestamp_response REAL,
                    duration_ms REAL NOT NULL,

                    -- Payload information
                    payload_size INTEGER NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_preview TEXT NOT NULL,
                    raw_payload BLOB NOT NULL,

                    -- Protocol information
                    protocol TEXT NOT NULL,
                    message_type TEXT,
                    state_at_send TEXT,
                    mutation_strategy TEXT,
                    mutators_applied TEXT,

                    -- Execution results
                    result TEXT NOT NULL,
                    response_size INTEGER,
                    response_preview TEXT,
                    response_data BLOB,

                    PRIMARY KEY (session_id, sequence_number)
                )
            """)

            # Critical indexes for performance
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON executions(session_id, timestamp_sent)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_result
                ON executions(session_id, result)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_test_case
                ON executions(test_case_id)
            """)

            # Add new columns for schema migrations
            new_columns = [
                ("mutation_strategy", "ALTER TABLE executions ADD COLUMN mutation_strategy TEXT"),
                ("mutators_applied", "ALTER TABLE executions ADD COLUMN mutators_applied TEXT"),
                # Orchestrated session columns
                ("stage_name", "ALTER TABLE executions ADD COLUMN stage_name TEXT"),
                ("context_snapshot", "ALTER TABLE executions ADD COLUMN context_snapshot TEXT"),
                ("parsed_fields", "ALTER TABLE executions ADD COLUMN parsed_fields TEXT"),
                ("connection_sequence", "ALTER TABLE executions ADD COLUMN connection_sequence INTEGER DEFAULT 0"),
            ]
            for column, ddl in new_columns:
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    logger.debug("history_column_exists", column=column)

            conn.commit()
            logger.info("database_schema_initialized", db_path=self.db_path)
        finally:
            conn.close()

    def start_background_writer(self) -> bool:
        """
        Start the background writer task.

        Returns:
            True if writer started or already running, False if no event loop available
        """
        if self._writer_task is not None and not self._writer_task.done():
            return True  # Already running

        try:
            loop = asyncio.get_running_loop()
            self._writer_task = loop.create_task(self._background_writer())
            logger.info("background_writer_started")
            return True
        except RuntimeError:
            # No event loop - caller should use synchronous write
            logger.warning("background_writer_failed_no_event_loop")
            return False

    async def shutdown(self):
        """Gracefully shutdown the background writer."""
        self._shutdown = True
        if self._writer_task and not self._writer_task.done():
            # Process remaining queue
            while not self._write_queue.empty():
                await asyncio.sleep(0.1)
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
        logger.info("history_store_shutdown_complete")

    async def flush(self, timeout: float = 5.0) -> bool:
        """
        Flush all pending records to SQLite synchronously.

        Called when stopping a session to ensure records are persisted
        before the session is marked complete.

        Args:
            timeout: Maximum seconds to wait for flush

        Returns:
            True if flush completed, False if timed out
        """
        # Collect all pending records from the queue
        pending = []
        while not self._write_queue.empty():
            try:
                pending.append(self._write_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not pending:
            logger.debug("flush_no_pending_records")
            return True

        logger.info("flushing_history_store", pending_records=len(pending))

        # Write directly to SQLite (bypasses background writer race condition)
        try:
            await asyncio.to_thread(self._write_batch, pending)
            logger.info("history_flush_complete", flushed_records=len(pending))
            return True
        except Exception as exc:
            logger.error("history_flush_failed", error=str(exc), lost_records=len(pending))
            return False

    async def _background_writer(self):
        """Background task that batches and writes records to SQLite."""
        logger.info("background_writer_loop_started")

        while not self._shutdown:
            batch = []
            try:
                # Wait for first record or timeout
                try:
                    first_record = await asyncio.wait_for(
                        self._write_queue.get(), timeout=1.0
                    )
                    batch.append(first_record)
                except asyncio.TimeoutError:
                    continue

                # Collect up to 100 more records without blocking
                while len(batch) < 100 and not self._write_queue.empty():
                    try:
                        batch.append(self._write_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                # Write batch in thread pool to avoid blocking event loop
                if batch:
                    await asyncio.to_thread(self._write_batch, batch)
                    logger.debug("batch_written", count=len(batch))

            except Exception as exc:
                logger.error("background_writer_error", error=str(exc))
                await asyncio.sleep(1.0)  # Back off on error

    def _write_batch(self, records: List[TestCaseExecutionRecord]):
        """Write a batch of records to SQLite (blocking, runs in thread pool)."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO executions (
                    session_id, sequence_number, test_case_id,
                    timestamp_sent, timestamp_response, duration_ms,
                    payload_size, payload_hash, payload_preview, raw_payload,
                    protocol, message_type, state_at_send,
                    mutation_strategy, mutators_applied,
                    result, response_size, response_preview, response_data,
                    stage_name, context_snapshot, parsed_fields, connection_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        rec.session_id,
                        rec.sequence_number,
                        rec.test_case_id,
                        rec.timestamp_sent.timestamp(),
                        rec.timestamp_response.timestamp() if rec.timestamp_response else None,
                        rec.duration_ms,
                        rec.payload_size,
                        rec.payload_hash,
                        rec.payload_preview,
                        base64.b64decode(rec.raw_payload_b64),  # Store raw bytes
                        rec.protocol,
                        rec.message_type,
                        rec.state_at_send,
                        rec.mutation_strategy,
                        json.dumps(rec.mutators_applied or []),
                        rec.result.value,
                        rec.response_size,
                        rec.response_preview,
                        base64.b64decode(rec.raw_response_b64) if rec.raw_response_b64 else None,
                        rec.stage_name,
                        json.dumps(_json_safe(rec.context_snapshot)) if rec.context_snapshot else None,
                        json.dumps(_json_safe(rec.parsed_fields)) if rec.parsed_fields else None,
                        rec.connection_sequence,
                    )
                    for rec in records
                ],
            )
            conn.commit()
        except Exception as exc:
            logger.error("batch_write_failed", error=str(exc), batch_size=len(records))
            raise
        finally:
            conn.close()

    def reset_session(self, session_id: str) -> None:
        """Clear cached sequence tracking for a session."""
        self._sequence_counters.pop(session_id, None)

    def get_max_sequence(self, session_id: str) -> int:
        """Return the highest recorded sequence number for a session."""
        cache = self._recent_cache.get(session_id)
        if cache:
            try:
                return cache[-1].sequence_number
            except IndexError:
                logger.debug(
                    "empty_cache_for_session",
                    session_id=session_id
                )

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT MAX(sequence_number) FROM executions WHERE session_id = ?",
                (session_id,),
            )
            result = cursor.fetchone()
            return result[0] or 0
        finally:
            conn.close()

    def _next_sequence_number(self, session_id: str) -> int:
        """Allocate the next sequence number for a session."""
        current = self._sequence_counters.get(session_id)
        if current is None:
            current = self.get_max_sequence(session_id)
        current += 1
        self._sequence_counters[session_id] = current
        return current

    def record(
        self,
        session: FuzzSession,
        test_case: TestCase,
        timestamp_sent: datetime,
        timestamp_response: datetime,
        result: TestCaseResult,
        response: Optional[bytes],
        message_type: Optional[str] = None,
        state_at_send: Optional[str] = None,
        stage_name: Optional[str] = None,
        context_snapshot: Optional[Dict] = None,
        parsed_fields: Optional[Dict] = None,
        connection_sequence: int = 0,
    ) -> TestCaseExecutionRecord:
        """
        Record a test case execution synchronously.

        Creates the record and queues it for async batch writing to SQLite.
        Also updates the memory cache for fast recent-test queries.

        Args:
            session: The fuzzing session
            test_case: The test case that was executed
            timestamp_sent: When the request was sent
            timestamp_response: When the response was received
            result: The execution result
            response: Response bytes (if any)
            message_type: Protocol message type
            state_at_send: State machine state when sent
            stage_name: Protocol stage (for orchestrated sessions)
            context_snapshot: ProtocolContext snapshot for replay
            parsed_fields: Parsed field values for re-serialization
            connection_sequence: Position within current connection
        """
        sequence_num = self._next_sequence_number(session.id)
        duration_ms = (timestamp_response - timestamp_sent).total_seconds() * 1000

        record = TestCaseExecutionRecord(
            test_case_id=test_case.id,
            session_id=session.id,
            sequence_number=sequence_num,
            timestamp_sent=timestamp_sent,
            timestamp_response=timestamp_response,
            duration_ms=duration_ms,
            payload_size=len(test_case.data),
            payload_hash=hashlib.sha256(test_case.data).hexdigest(),
            payload_preview=test_case.data[:64].hex(),
            protocol=session.protocol,
            message_type=message_type,
            state_at_send=state_at_send,
            result=result,
            response_size=len(response) if response is not None else None,
            response_preview=response[:64].hex() if response is not None else None,
            raw_payload_b64=base64.b64encode(test_case.data).decode("utf-8"),
            raw_response_b64=base64.b64encode(response).decode("utf-8") if response else None,
            mutation_strategy=test_case.mutation_strategy,
            mutators_applied=list(test_case.mutators_applied or []),
            stage_name=stage_name,
            context_snapshot=context_snapshot,
            parsed_fields=parsed_fields,
            connection_sequence=connection_sequence,
        )

        # Update memory cache (always available for real-time queries)
        cache = self._recent_cache.setdefault(session.id, deque(maxlen=self.memory_cache_size))
        cache.append(record)

        # Try to start background writer if not running
        writer_running = self._writer_task is not None and not self._writer_task.done()
        if not writer_running:
            writer_running = self.start_background_writer()

        if writer_running:
            # Queue for async batch write (non-blocking)
            try:
                self._write_queue.put_nowait(record)
            except asyncio.QueueFull:
                logger.warning("write_queue_full", writing_sync=True)
                # Fallback to synchronous write
                self._write_batch([record])
        else:
            # No event loop available - write synchronously
            self._write_batch([record])

        return record

    def record_direct(self, record: TestCaseExecutionRecord) -> TestCaseExecutionRecord:
        """
        Record a pre-built TestCaseExecutionRecord.

        Used by StageRunner for bootstrap executions where the record
        is constructed with custom sequence numbers and fields.

        Args:
            record: Pre-built execution record

        Returns:
            The same record after caching and queueing
        """
        # Update memory cache
        cache = self._recent_cache.setdefault(record.session_id, deque(maxlen=self.memory_cache_size))
        cache.append(record)

        # Try to start background writer if not running
        writer_running = self._writer_task is not None and not self._writer_task.done()
        if not writer_running:
            writer_running = self.start_background_writer()

        if writer_running:
            # Queue for async batch write
            try:
                self._write_queue.put_nowait(record)
            except asyncio.QueueFull:
                logger.warning("write_queue_full", writing_sync=True)
                self._write_batch([record])
        else:
            # No event loop - write synchronously
            self._write_batch([record])

        return record

    def list(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[TestCaseExecutionRecord]:
        """
        List execution records, merging SQLite and cache for consistency.

        Strategy:
        - Always query SQLite for the requested page
        - For first page (offset=0), merge in cache records that may not
          have been written to SQLite yet (handles async write lag)
        - For paginated queries (offset > 0): SQLite only, as cache
          only holds the most recent records

        Returns records in descending order (most recent first).
        """
        # Query from SQLite
        db_records = self._query_from_db(session_id, limit, offset, since, until)

        # For first page without filters, merge in unflushed cache records
        if offset == 0 and not since and not until:
            cache = self._recent_cache.get(session_id)
            if cache:
                # Find cache records not yet in SQLite results
                db_sequences = {r.sequence_number for r in db_records}
                unflushed = [r for r in cache if r.sequence_number not in db_sequences]
                if unflushed:
                    # Merge and re-sort by sequence descending, then limit
                    merged = sorted(
                        db_records + unflushed,
                        key=lambda r: r.sequence_number,
                        reverse=True,
                    )[:limit]
                    logger.debug(
                        "list_merged_cache",
                        session_id=session_id,
                        db_count=len(db_records),
                        unflushed_count=len(unflushed),
                        merged_count=len(merged),
                    )
                    return merged

        return db_records

    def list_for_replay(
        self,
        session_id: str,
        up_to_sequence: int,
    ) -> List[TestCaseExecutionRecord]:
        """
        Get execution records for replay in ASCENDING order.

        Replay requires processing records in order (1, 2, 3, ..., N) to
        correctly rebuild protocol state. Unlike list() which returns
        descending order, this returns ascending order.

        Args:
            session_id: Session to query
            up_to_sequence: Get records 1 through this sequence number

        Returns:
            List of records in ascending order
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            cursor = conn.execute(
                """
                SELECT * FROM executions
                WHERE session_id = ?
                  AND sequence_number <= ?
                ORDER BY sequence_number ASC
                """,
                (session_id, up_to_sequence),
            )
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def get_first_sequence(self, session_id: str) -> int:
        """Get the first available sequence number for a session."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT MIN(sequence_number) FROM executions WHERE session_id = ?",
                (session_id,),
            )
            result = cursor.fetchone()
            return result[0] or 0
        finally:
            conn.close()

    def _row_to_record(self, row: sqlite3.Row) -> TestCaseExecutionRecord:
        """Convert a SQLite row to a TestCaseExecutionRecord."""
        # Handle new columns that may not exist in older databases
        stage_name = row["stage_name"] if "stage_name" in row.keys() else None
        context_snapshot = None
        if "context_snapshot" in row.keys() and row["context_snapshot"]:
            try:
                context_snapshot = json.loads(row["context_snapshot"])
            except (json.JSONDecodeError, TypeError):
                pass
        parsed_fields = None
        if "parsed_fields" in row.keys() and row["parsed_fields"]:
            try:
                parsed_fields = json.loads(row["parsed_fields"])
            except (json.JSONDecodeError, TypeError):
                pass
        connection_sequence = row["connection_sequence"] if "connection_sequence" in row.keys() else 0

        return TestCaseExecutionRecord(
            test_case_id=row["test_case_id"],
            session_id=row["session_id"],
            sequence_number=row["sequence_number"],
            timestamp_sent=datetime.fromtimestamp(row["timestamp_sent"]),
            timestamp_response=datetime.fromtimestamp(row["timestamp_response"])
            if row["timestamp_response"]
            else None,
            duration_ms=row["duration_ms"],
            payload_size=row["payload_size"],
            payload_hash=row["payload_hash"],
            payload_preview=row["payload_preview"],
            protocol=row["protocol"],
            message_type=row["message_type"],
            state_at_send=row["state_at_send"],
            mutation_strategy=row["mutation_strategy"],
            mutators_applied=json.loads(row["mutators_applied"] or "[]"),
            result=TestCaseResult(row["result"]),
            response_size=row["response_size"],
            response_preview=row["response_preview"],
            raw_payload_b64=base64.b64encode(row["raw_payload"]).decode("utf-8"),
            raw_response_b64=base64.b64encode(row["response_data"]).decode("utf-8")
            if row["response_data"]
            else None,
            stage_name=stage_name,
            context_snapshot=context_snapshot,
            parsed_fields=parsed_fields,
            connection_sequence=connection_sequence,
        )

    def _query_from_db(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[TestCaseExecutionRecord]:
        """Query records from SQLite (blocking, should be fast with indexes)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            query = """
                SELECT * FROM executions
                WHERE session_id = ?
            """
            params = [session_id]

            if since:
                query += " AND timestamp_sent >= ?"
                params.append(since.timestamp())

            if until:
                query += " AND timestamp_sent <= ?"
                params.append(until.timestamp())

            query += " ORDER BY sequence_number DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            records = [self._row_to_record(row) for row in rows]
            return records
        finally:
            conn.close()

    def total_count(self, session_id: str) -> int:
        """
        Get total count of executions for a session.

        Uses sequence counter when available (most accurate for active
        sessions), falls back to max sequence from DB/cache for inactive
        sessions.
        """
        # For active sessions, sequence counter is authoritative
        sequence = self._sequence_counters.get(session_id)
        if sequence is not None:
            return sequence

        # For inactive sessions, get max sequence from cache or DB
        cache_max = 0
        cache = self._recent_cache.get(session_id)
        if cache:
            try:
                cache_max = cache[-1].sequence_number
            except (IndexError, AttributeError):
                pass

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT MAX(sequence_number) FROM executions WHERE session_id = ?",
                (session_id,),
            )
            db_max = cursor.fetchone()[0] or 0
        finally:
            conn.close()

        return max(db_max, cache_max)

    def find_by_sequence(
        self, session_id: str, sequence_number: int
    ) -> Optional[TestCaseExecutionRecord]:
        """Find a record by sequence number (fast - uses primary key)."""
        # Check memory cache first
        cache = self._recent_cache.get(session_id, [])
        for record in cache:
            if record.sequence_number == sequence_number:
                return record

        # Query from DB
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            cursor = conn.execute(
                "SELECT * FROM executions WHERE session_id = ? AND sequence_number = ?",
                (session_id, sequence_number),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_record(row)
        finally:
            conn.close()

    def find_at_time(
        self, session_id: str, timestamp: datetime
    ) -> Optional[TestCaseExecutionRecord]:
        """Find a record at a specific timestamp (uses indexed query)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            # Find record where timestamp falls between sent and response
            cursor = conn.execute(
                """
                SELECT * FROM executions
                WHERE session_id = ?
                  AND timestamp_sent <= ?
                  AND (timestamp_response IS NULL OR timestamp_response >= ?)
                ORDER BY timestamp_sent DESC
                LIMIT 1
                """,
                (session_id, timestamp.timestamp(), timestamp.timestamp()),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_record(row)
        finally:
            conn.close()
