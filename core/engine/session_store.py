"""
Session persistence layer - SQLite-backed storage for fuzzing sessions.

Allows sessions to survive container restarts and enables graceful resume.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from core.models import FuzzSession, FuzzSessionStatus

logger = structlog.get_logger()


class SessionStore:
    """
    Persistent storage for fuzzing sessions.

    Stores session configuration and state in SQLite, allowing:
    - Recovery after restart
    - Session resume capability
    - Historical session tracking
    """

    def __init__(self, db_path: str = "data/sessions.db"):
        self.db_path = db_path
        self._init_database()
        logger.info("session_store_initialized", db_path=db_path)

    def _init_database(self):
        """Create database schema if it doesn't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    protocol TEXT NOT NULL,
                    target_host TEXT NOT NULL,
                    target_port INTEGER NOT NULL,
                    transport TEXT NOT NULL,

                    -- Session status and lifecycle
                    status TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,

                    -- Progress tracking
                    total_tests INTEGER NOT NULL DEFAULT 0,
                    crashes INTEGER NOT NULL DEFAULT 0,
                    hangs INTEGER NOT NULL DEFAULT 0,
                    anomalies INTEGER NOT NULL DEFAULT 0,
                    current_iteration INTEGER NOT NULL DEFAULT 0,
                    max_iterations INTEGER,

                    -- Configuration (stored as JSON)
                    enabled_mutators TEXT,
                    seed_corpus TEXT,
                    mutation_mode TEXT,
                    structure_aware_weight INTEGER,
                    timeout_per_test_ms INTEGER,
                    rate_limit_per_second REAL,

                    -- Stateful fuzzing state
                    current_state TEXT,
                    state_coverage TEXT,  -- JSON
                    transition_coverage TEXT,  -- JSON
                    coverage_snapshot TEXT,  -- JSON

                    -- Targeting configuration
                    fuzzing_mode TEXT,
                    target_state TEXT,
                    mutable_fields TEXT,  -- JSON
                    field_mutation_counts TEXT,  -- JSON
                    field_mutation_config TEXT,  -- JSON

                    -- Error tracking
                    error_message TEXT,

                    -- Full session config for exact restore
                    full_config TEXT  -- JSON blob with all fields
                )
            """)

            # Indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status
                ON sessions(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_protocol
                ON sessions(protocol)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created
                ON sessions(created_at DESC)
            """)

            conn.commit()
            logger.debug("session_store_schema_created")

        finally:
            conn.close()

    def save_session(self, session: FuzzSession) -> None:
        """
        Persist a session to database.

        Args:
            session: FuzzSession to save
        """
        conn = sqlite3.connect(self.db_path)
        try:
            # Serialize complex fields to JSON
            session_data = {
                "id": session.id,
                "protocol": session.protocol,
                "target_host": session.target_host,
                "target_port": session.target_port,
                "transport": session.transport.value,
                "status": session.status.value,
                "execution_mode": session.execution_mode.value,
                "created_at": session.created_at.timestamp() if session.created_at else datetime.utcnow().timestamp(),
                "started_at": session.started_at.timestamp() if session.started_at else None,
                "completed_at": session.completed_at.timestamp() if session.completed_at else None,
                "total_tests": session.total_tests,
                "crashes": session.crashes,
                "hangs": session.hangs,
                "anomalies": session.anomalies,
                "current_iteration": session.total_tests,  # Use total_tests as iteration counter
                "max_iterations": session.max_iterations,
                "enabled_mutators": json.dumps(session.enabled_mutators),
                "seed_corpus": json.dumps(session.seed_corpus),
                "mutation_mode": session.mutation_mode,
                "structure_aware_weight": session.structure_aware_weight,
                "timeout_per_test_ms": session.timeout_per_test_ms,
                "rate_limit_per_second": session.rate_limit_per_second,
                "current_state": session.current_state,
                "state_coverage": json.dumps(session.state_coverage) if session.state_coverage else None,
                "transition_coverage": json.dumps(session.transition_coverage) if session.transition_coverage else None,
                "coverage_snapshot": json.dumps(session.coverage_snapshot) if session.coverage_snapshot else None,
                "fuzzing_mode": session.fuzzing_mode,
                "target_state": session.target_state,
                "mutable_fields": json.dumps(session.mutable_fields) if session.mutable_fields else None,
                "field_mutation_counts": json.dumps(session.field_mutation_counts) if session.field_mutation_counts else None,
                "field_mutation_config": json.dumps(session.field_mutation_config) if session.field_mutation_config else None,
                "error_message": session.error_message,
                "full_config": session.model_dump_json(),
            }

            conn.execute("""
                INSERT OR REPLACE INTO sessions (
                    id, protocol, target_host, target_port, transport,
                    status, execution_mode, created_at, started_at, completed_at,
                    total_tests, crashes, hangs, anomalies, current_iteration, max_iterations,
                    enabled_mutators, seed_corpus, mutation_mode, structure_aware_weight,
                    timeout_per_test_ms, rate_limit_per_second,
                    current_state, state_coverage, transition_coverage, coverage_snapshot,
                    fuzzing_mode, target_state, mutable_fields, field_mutation_counts, field_mutation_config,
                    error_message, full_config
                ) VALUES (
                    :id, :protocol, :target_host, :target_port, :transport,
                    :status, :execution_mode, :created_at, :started_at, :completed_at,
                    :total_tests, :crashes, :hangs, :anomalies, :current_iteration, :max_iterations,
                    :enabled_mutators, :seed_corpus, :mutation_mode, :structure_aware_weight,
                    :timeout_per_test_ms, :rate_limit_per_second,
                    :current_state, :state_coverage, :transition_coverage, :coverage_snapshot,
                    :fuzzing_mode, :target_state, :mutable_fields, :field_mutation_counts, :field_mutation_config,
                    :error_message, :full_config
                )
            """, session_data)

            conn.commit()
            logger.debug("session_saved", session_id=session.id, status=session.status.value)

        finally:
            conn.close()

    def load_session(self, session_id: str) -> Optional[FuzzSession]:
        """
        Load a session from database.

        Args:
            session_id: Session ID to load

        Returns:
            FuzzSession if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT full_config FROM sessions WHERE id = ?",
                (session_id,)
            ).fetchone()

            if not row:
                return None

            # Deserialize from full_config JSON
            session = FuzzSession.model_validate_json(row["full_config"])
            logger.debug("session_loaded", session_id=session_id)
            return session

        except Exception as e:
            logger.error("session_load_failed", session_id=session_id, error=str(e))
            return None
        finally:
            conn.close()

    def load_all_sessions(self, status_filter: Optional[List[str]] = None) -> List[FuzzSession]:
        """
        Load all sessions, optionally filtered by status.

        Args:
            status_filter: List of status values to filter by (e.g., ['running', 'paused'])

        Returns:
            List of FuzzSession objects
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            if status_filter:
                placeholders = ",".join("?" * len(status_filter))
                query = f"SELECT full_config FROM sessions WHERE status IN ({placeholders}) ORDER BY created_at DESC"
                rows = conn.execute(query, status_filter).fetchall()
            else:
                rows = conn.execute("SELECT full_config FROM sessions ORDER BY created_at DESC").fetchall()

            sessions = []
            for row in rows:
                try:
                    session = FuzzSession.model_validate_json(row["full_config"])
                    sessions.append(session)
                except Exception as e:
                    logger.warning("session_deserialization_failed", error=str(e))
                    continue

            logger.debug("sessions_loaded", count=len(sessions), filter=status_filter)
            return sessions

        finally:
            conn.close()

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session from database.

        Args:
            session_id: Session ID to delete

        Returns:
            True if deleted, False if not found
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info("session_deleted_from_db", session_id=session_id)
            return deleted
        finally:
            conn.close()

    def get_session_count(self, status: Optional[str] = None) -> int:
        """
        Get count of sessions, optionally filtered by status.

        Args:
            status: Optional status to filter by

        Returns:
            Count of matching sessions
        """
        conn = sqlite3.connect(self.db_path)
        try:
            if status:
                count = conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE status = ?",
                    (status,)
                ).fetchone()[0]
            else:
                count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            return count
        finally:
            conn.close()

    def cleanup_old_sessions(self, days: int = 30, statuses: List[str] = None) -> int:
        """
        Delete old completed/failed sessions.

        Args:
            days: Delete sessions older than this many days
            statuses: Only delete sessions with these statuses (default: completed, failed)

        Returns:
            Number of sessions deleted
        """
        if statuses is None:
            statuses = ["completed", "failed"]

        cutoff = datetime.utcnow().timestamp() - (days * 24 * 3600)

        conn = sqlite3.connect(self.db_path)
        try:
            placeholders = ",".join("?" * len(statuses))
            cursor = conn.execute(
                f"""
                DELETE FROM sessions
                WHERE status IN ({placeholders})
                AND created_at < ?
                """,
                (*statuses, cutoff)
            )
            conn.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info("old_sessions_cleaned", count=deleted, older_than_days=days)
            return deleted
        finally:
            conn.close()
