"""
Decomposed Session Models - Structured session data containers.

This module provides a cleaner, structured organization for session data
by grouping related fields into focused sub-models instead of one flat model.

Component Overview:
-------------------
The session models decompose FuzzSession's 60+ fields into logical groups:

1. SessionConfig - Immutable settings defined at creation:
   - Protocol and target configuration
   - Mutation settings
   - Targeting configuration (state, mode, fields)
   - Lifecycle settings (reset intervals, termination)

2. SessionStats - Counters updated during fuzzing:
   - Test counts (total, crashes, hangs, anomalies)
   - Reset tracking
   - Field mutation counts

3. SessionState - Runtime status:
   - Current status (IDLE, RUNNING, etc.)
   - Error messages
   - Current protocol state
   - Pending flags

4. CoverageState - Coverage tracking:
   - State visit counts
   - Transition counts
   - Coverage snapshots

5. OrchestrationState - Protocol stack state:
   - Bootstrap/teardown configuration
   - Connection mode and ID
   - Heartbeat state

6. SessionTimestamps - Lifecycle timing:
   - Created, started, completed timestamps

7. ComposedSession - Aggregate container:
   - Combines all sub-models
   - Bidirectional conversion to/from FuzzSession

Key Benefits:
------------
- Better code organization (find related fields easily)
- Clearer interfaces (pass SessionConfig, not full session)
- Type safety (each sub-model validates its fields)
- Testability (test sub-models in isolation)

Backward Compatibility:
----------------------
The FuzzSession model in core/models.py remains the source of truth
for persistence and API compatibility. These models are used internally
by the decomposed components.

Usage Example:
-------------
    # Create from existing FuzzSession
    composed = ComposedSession.from_fuzz_session(session)

    # Access grouped fields
    print(f"Protocol: {composed.config.protocol}")
    print(f"Crashes: {composed.stats.crashes}")
    print(f"Status: {composed.state.status}")
    print(f"Coverage: {composed.coverage.coverage_percentage}%")

    # Convert back when needed
    flat_session = composed.to_fuzz_session()

Sub-Model Guidelines:
--------------------
- SessionConfig: Treat as immutable after creation
- SessionStats: Only increment, never decrement
- SessionState: Update via state machine transitions
- CoverageState: Synced from StatefulFuzzingSession
- OrchestrationState: Updated by StageRunner/HeartbeatScheduler

Note:
----
This module is part of the Phase 5 orchestrator decomposition. It provides
structured session representations for the extracted components.

See Also:
--------
- core/models.py - Canonical FuzzSession model
- core/engine/session_manager.py - Uses these for internal organization
- core/engine/fuzzing_loop.py - Uses these for cleaner interfaces
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.models import ExecutionMode, FuzzSessionStatus, TransportProtocol


class SessionConfig(BaseModel):
    """
    Session configuration - immutable settings defined at creation.

    These values are set when the session is created and don't change
    during the fuzzing run.
    """

    protocol: str
    target_host: str
    target_port: int
    transport: TransportProtocol = TransportProtocol.TCP
    execution_mode: ExecutionMode = ExecutionMode.CORE
    timeout_per_test_ms: int = 5000
    rate_limit_per_second: Optional[int] = None
    max_iterations: Optional[int] = None

    # Mutation configuration
    mutation_mode: Optional[str] = None
    structure_aware_weight: Optional[int] = None
    enabled_mutators: List[str] = Field(default_factory=list)

    # Targeting configuration
    target_state: Optional[str] = None
    fuzzing_mode: str = "random"
    mutable_fields: Optional[List[str]] = None
    field_mutation_config: Optional[Dict[str, Any]] = None

    # Session lifecycle configuration
    session_reset_interval: Optional[int] = None
    enable_termination_fuzzing: bool = False


class SessionStats(BaseModel):
    """
    Session statistics - counters updated during fuzzing.

    These values are updated as the session runs and track
    overall progress and findings.
    """

    total_tests: int = 0
    crashes: int = 0
    hangs: int = 0
    anomalies: int = 0
    unique_crashes: int = 0
    session_resets: int = 0
    termination_tests: int = 0
    tests_since_last_reset: int = 0

    # Field mutation tracking
    field_mutation_counts: Dict[str, int] = Field(default_factory=dict)


class SessionState(BaseModel):
    """
    Session runtime state - current status and error info.

    These values track the current state of the session and any
    error conditions.
    """

    status: FuzzSessionStatus = FuzzSessionStatus.IDLE
    error_message: Optional[str] = None
    current_state: Optional[str] = None
    current_stage: str = "default"
    termination_reset_pending: bool = False


class CoverageState(BaseModel):
    """
    Coverage tracking state - state and transition coverage.

    These values track coverage metrics for stateful fuzzing,
    including state visits and transition counts.
    """

    state_coverage: Dict[str, int] = Field(default_factory=dict)
    transition_coverage: Dict[str, int] = Field(default_factory=dict)
    coverage_snapshot: Optional[Dict[str, Any]] = None

    @property
    def coverage_percentage(self) -> float:
        """Returns % of states visited vs total in protocol."""
        if not self.state_coverage:
            return 0.0
        total_states = len(self.state_coverage)
        if total_states == 0:
            return 0.0
        visited = sum(1 for count in self.state_coverage.values() if count > 0)
        return (visited / total_states) * 100.0

    @property
    def unexplored_states(self) -> List[str]:
        """States defined in protocol but never reached."""
        return [state for state, count in self.state_coverage.items() if count == 0]


class OrchestrationState(BaseModel):
    """
    Orchestration state - protocol stack and connection management.

    These values track the state of orchestrated protocol sessions
    with bootstrap/teardown stages and persistent connections.
    """

    protocol_stack_config: Optional[List[Dict[str, Any]]] = None
    connection_mode: str = "per_test"
    connection_id: Optional[str] = None
    reconnect_count: int = 0
    context: Optional[Dict[str, Any]] = None

    # Heartbeat state
    heartbeat_enabled: bool = False
    heartbeat_last_sent: Optional[datetime] = None
    heartbeat_last_ack: Optional[datetime] = None
    heartbeat_failures: int = 0


class SessionTimestamps(BaseModel):
    """
    Session timestamps - lifecycle timing.
    """

    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class ComposedSession:
    """
    Composed session - aggregates all session sub-models.

    This provides a structured view of a session, grouping related
    fields into focused sub-models. It can be created from a FuzzSession
    for use in internal components.

    Note: This is a dataclass (not Pydantic) to avoid serialization
    complexity. Use the individual sub-models for API responses.
    """

    id: str
    config: SessionConfig
    stats: SessionStats
    state: SessionState
    coverage: CoverageState
    orchestration: OrchestrationState
    timestamps: SessionTimestamps
    seed_corpus: List[str] = field(default_factory=list)
    behavior_state: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_fuzz_session(cls, session: "FuzzSession") -> "ComposedSession":
        """
        Create a ComposedSession from a FuzzSession.

        This extracts the fields from the flat FuzzSession model
        into the structured sub-models.
        """
        from core.models import FuzzSession

        config = SessionConfig(
            protocol=session.protocol,
            target_host=session.target_host,
            target_port=session.target_port,
            transport=session.transport,
            execution_mode=session.execution_mode,
            timeout_per_test_ms=session.timeout_per_test_ms,
            rate_limit_per_second=session.rate_limit_per_second,
            max_iterations=session.max_iterations,
            mutation_mode=session.mutation_mode,
            structure_aware_weight=session.structure_aware_weight,
            enabled_mutators=session.enabled_mutators,
            target_state=session.target_state,
            fuzzing_mode=session.fuzzing_mode,
            mutable_fields=session.mutable_fields,
            field_mutation_config=session.field_mutation_config,
            session_reset_interval=session.session_reset_interval,
            enable_termination_fuzzing=session.enable_termination_fuzzing,
        )

        stats = SessionStats(
            total_tests=session.total_tests,
            crashes=session.crashes,
            hangs=session.hangs,
            anomalies=session.anomalies,
            unique_crashes=session.unique_crashes,
            session_resets=session.session_resets,
            termination_tests=session.termination_tests,
            tests_since_last_reset=session.tests_since_last_reset,
            field_mutation_counts=session.field_mutation_counts,
        )

        state = SessionState(
            status=session.status,
            error_message=session.error_message,
            current_state=session.current_state,
            current_stage=session.current_stage,
            termination_reset_pending=session.termination_reset_pending,
        )

        coverage = CoverageState(
            state_coverage=session.state_coverage,
            transition_coverage=session.transition_coverage,
            coverage_snapshot=session.coverage_snapshot,
        )

        orchestration = OrchestrationState(
            protocol_stack_config=session.protocol_stack_config,
            connection_mode=session.connection_mode,
            connection_id=session.connection_id,
            reconnect_count=session.reconnect_count,
            context=session.context,
            heartbeat_enabled=session.heartbeat_enabled,
            heartbeat_last_sent=session.heartbeat_last_sent,
            heartbeat_last_ack=session.heartbeat_last_ack,
            heartbeat_failures=session.heartbeat_failures,
        )

        timestamps = SessionTimestamps(
            created_at=session.created_at,
            started_at=session.started_at,
            completed_at=session.completed_at,
        )

        return cls(
            id=session.id,
            config=config,
            stats=stats,
            state=state,
            coverage=coverage,
            orchestration=orchestration,
            timestamps=timestamps,
            seed_corpus=session.seed_corpus,
            behavior_state=session.behavior_state,
        )

    def to_fuzz_session(self) -> "FuzzSession":
        """
        Convert back to a FuzzSession.

        This flattens the structured sub-models back into the
        flat FuzzSession model for persistence and API compatibility.
        """
        from core.models import FuzzSession

        return FuzzSession(
            id=self.id,
            protocol=self.config.protocol,
            target_host=self.config.target_host,
            target_port=self.config.target_port,
            transport=self.config.transport,
            execution_mode=self.config.execution_mode,
            timeout_per_test_ms=self.config.timeout_per_test_ms,
            rate_limit_per_second=self.config.rate_limit_per_second,
            max_iterations=self.config.max_iterations,
            mutation_mode=self.config.mutation_mode,
            structure_aware_weight=self.config.structure_aware_weight,
            enabled_mutators=self.config.enabled_mutators,
            target_state=self.config.target_state,
            fuzzing_mode=self.config.fuzzing_mode,
            mutable_fields=self.config.mutable_fields,
            field_mutation_config=self.config.field_mutation_config,
            session_reset_interval=self.config.session_reset_interval,
            enable_termination_fuzzing=self.config.enable_termination_fuzzing,
            status=self.state.status,
            error_message=self.state.error_message,
            current_state=self.state.current_state,
            current_stage=self.state.current_stage,
            termination_reset_pending=self.state.termination_reset_pending,
            total_tests=self.stats.total_tests,
            crashes=self.stats.crashes,
            hangs=self.stats.hangs,
            anomalies=self.stats.anomalies,
            unique_crashes=self.stats.unique_crashes,
            session_resets=self.stats.session_resets,
            termination_tests=self.stats.termination_tests,
            tests_since_last_reset=self.stats.tests_since_last_reset,
            field_mutation_counts=self.stats.field_mutation_counts,
            state_coverage=self.coverage.state_coverage,
            transition_coverage=self.coverage.transition_coverage,
            coverage_snapshot=self.coverage.coverage_snapshot,
            protocol_stack_config=self.orchestration.protocol_stack_config,
            connection_mode=self.orchestration.connection_mode,
            connection_id=self.orchestration.connection_id,
            reconnect_count=self.orchestration.reconnect_count,
            context=self.orchestration.context,
            heartbeat_enabled=self.orchestration.heartbeat_enabled,
            heartbeat_last_sent=self.orchestration.heartbeat_last_sent,
            heartbeat_last_ack=self.orchestration.heartbeat_last_ack,
            heartbeat_failures=self.orchestration.heartbeat_failures,
            created_at=self.timestamps.created_at,
            started_at=self.timestamps.started_at,
            completed_at=self.timestamps.completed_at,
            seed_corpus=self.seed_corpus,
            behavior_state=self.behavior_state,
        )
