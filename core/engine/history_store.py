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

            for column, ddl in [
                ("mutation_strategy", "ALTER TABLE executions ADD COLUMN mutation_strategy TEXT"),
                ("mutators_applied", "ALTER TABLE executions ADD COLUMN mutators_applied TEXT"),
            ]:
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    logger.debug("history_column_exists", column=column)

            conn.commit()
            logger.info("database_schema_initialized", db_path=self.db_path)
        finally:
            conn.close()

    def start_background_writer(self):
        """Start the background writer task (must be called from async context)."""
        if self._writer_task is None or self._writer_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._writer_task = loop.create_task(self._background_writer())
                logger.info("background_writer_started")
            except RuntimeError:
                # No event loop running yet - writer will start lazily on first record
                logger.debug("background_writer_deferred_no_event_loop")
                pass

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
                    result, response_size, response_preview, response_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                pass

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
    ) -> TestCaseExecutionRecord:
        """
        Record a test case execution synchronously.

        Creates the record and queues it for async batch writing to SQLite.
        Also updates the memory cache for fast recent-test queries.
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
        )

        # Update memory cache
        cache = self._recent_cache.setdefault(session.id, deque(maxlen=self.memory_cache_size))
        cache.append(record)

        # Start background writer if not running (lazy initialization)
        if self._writer_task is None or self._writer_task.done():
            self.start_background_writer()

        # Queue for async batch write (non-blocking)
        try:
            self._write_queue.put_nowait(record)
        except asyncio.QueueFull:
            logger.warning("write_queue_full", dropping_record=True)

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
        List execution records from SQLite.

        For recent queries (no filters), uses memory cache for speed.
        For filtered queries, queries SQLite directly.
        """
        # Fast path: recent tests with no filters
        if offset == 0 and not since and not until and limit <= self.memory_cache_size:
            cache = list(self._recent_cache.get(session_id, []))
            # Return in reverse order (most recent first)
            return list(reversed(cache))[:limit]

        # Slow path: query SQLite
        return self._query_from_db(session_id, limit, offset, since, until)

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

            records = []
            for row in rows:
                records.append(
                    TestCaseExecutionRecord(
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
                    )
                )

            return records
        finally:
            conn.close()

    def total_count(self, session_id: str) -> int:
        """Get total count of executions for a session from SQLite."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM executions WHERE session_id = ?", (session_id,)
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

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
            )
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
            )
        finally:
            conn.close()
