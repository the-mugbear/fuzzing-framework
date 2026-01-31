"""
Core data models
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class FuzzSessionStatus(str, Enum):
    """Fuzzing session status"""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class TestCaseResult(str, Enum):
    """Test case execution result"""

    PASS = "pass"
    CRASH = "crash"
    HANG = "hang"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    LOGICAL_FAILURE = "logical_failure"
    ANOMALY = "anomaly"


class TransportProtocol(str, Enum):
    """Network transport used to reach targets"""

    TCP = "tcp"
    UDP = "udp"


class ConnectionMode(str, Enum):
    """Connection lifecycle mode for orchestrated sessions"""

    PER_TEST = "per_test"
    PER_STAGE = "per_stage"
    SESSION = "session"


class ProtocolPlugin(BaseModel):
    """Protocol plugin definition"""

    name: str
    data_model: Dict[str, Any]
    state_model: Dict[str, Any]
    response_model: Optional[Dict[str, Any]] = None
    response_handlers: List[Dict[str, Any]] = Field(default_factory=list)
    description: Optional[str] = None
    author: Optional[str] = None
    version: Optional[str] = "1.0.0"
    transport: TransportProtocol = Field(
        default=TransportProtocol.TCP,
        description="Default transport to use when executing this protocol",
    )

    # Orchestrated session configuration (optional)
    protocol_stack: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Protocol stack for orchestrated sessions (bootstrap, fuzz_target, teardown stages)",
    )
    connection: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Connection lifecycle configuration",
    )
    heartbeat: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Heartbeat/keepalive configuration",
    )


class TestCase(BaseModel):
    """Individual test case"""

    id: str
    session_id: str
    seed_id: Optional[str] = None
    data: bytes
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    result: Optional[TestCaseResult] = None
    execution_time_ms: Optional[float] = None
    coverage_data: Optional[Dict[str, Any]] = None
    mutation_strategy: Optional[str] = None
    mutators_applied: List[str] = Field(default_factory=list)


class CrashReport(BaseModel):
    """Crash/finding report"""

    id: str
    session_id: str
    test_case_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    result_type: TestCaseResult
    signal: Optional[int] = None
    exit_code: Optional[int] = None
    stack_trace: Optional[str] = None
    reproducer_data: bytes
    response_data: Optional[bytes] = None
    response_preview: Optional[str] = None
    cpu_usage: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    severity: str = "unknown"


class AgentStatus(BaseModel):
    """Agent health and status"""

    agent_id: str
    hostname: str
    target_host: str
    target_port: int
    transport: TransportProtocol = TransportProtocol.TCP
    is_alive: bool
    last_heartbeat: datetime
    cpu_usage: float = 0.0
    memory_usage_mb: float = 0.0
    active_test_count: int = 0


class ExecutionMode(str, Enum):
    """Where test cases execute"""

    CORE = "core"
    AGENT = "agent"



class FuzzSession(BaseModel):
    """Fuzzing session configuration and state"""

    model_config = {"ser_json_inf_nan": "constants"}

    id: str
    protocol: str
    execution_mode: ExecutionMode = Field(default=ExecutionMode.CORE)
    status: FuzzSessionStatus = FuzzSessionStatus.IDLE
    target_host: str
    target_port: int
    transport: TransportProtocol = TransportProtocol.TCP
    seed_corpus: List[str] = Field(default_factory=list)
    enabled_mutators: List[str] = Field(default_factory=list)
    timeout_per_test_ms: int = 5000
    rate_limit_per_second: Optional[int] = Field(
        default=None, description="Maximum test cases per second (None = unlimited)"
    )
    mutation_mode: Optional[str] = Field(
        default=None, description="Mutation mode: structure_aware, byte_level, or hybrid"
    )
    structure_aware_weight: Optional[int] = Field(
        default=None, description="Percentage for structure-aware mutations in hybrid mode (0-100)"
    )
    max_iterations: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = Field(default=None)  # Error description if status is FAILED

    # Statistics
    total_tests: int = 0
    crashes: int = 0
    hangs: int = 0
    anomalies: int = 0
    unique_crashes: int = 0
    behavior_state: Dict[str, Any] = Field(default_factory=dict)
    coverage_snapshot: Optional[Dict[str, Any]] = None

    # NEW: Targeting configuration
    target_state: Optional[str] = Field(
        default=None, description="Focus fuzzing on specific state (for stateful protocols)"
    )
    fuzzing_mode: str = Field(
        default="random", description="Fuzzing strategy: random, breadth_first, depth_first, targeted"
    )
    mutable_fields: Optional[List[str]] = Field(
        default=None, description="Restrict mutations to specific fields (None = all mutable fields)"
    )
    field_mutation_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Per-field mutation configuration"
    )

    # NEW: State coverage tracking (live data, updated in real-time)
    state_coverage: Dict[str, int] = Field(
        default_factory=dict, description="State visit counts: {state_name: count}"
    )
    transition_coverage: Dict[str, int] = Field(
        default_factory=dict, description="Transition counts: {'FROM->TO': count}"
    )
    current_state: Optional[str] = Field(
        default=None, description="Current protocol state (for stateful protocols)"
    )

    # Session lifecycle configuration
    session_reset_interval: Optional[int] = Field(
        default=None, description="Reset protocol state every N test cases"
    )
    enable_termination_fuzzing: bool = Field(
        default=False, description="Periodically inject termination state transitions"
    )

    # Session lifecycle tracking
    session_resets: int = Field(default=0, description="Number of state machine resets")
    termination_tests: int = Field(default=0, description="Number of termination tests injected")
    tests_since_last_reset: int = Field(default=0, description="Tests executed since last reset")
    termination_reset_pending: bool = Field(
        default=False,
        description="Whether the session is waiting to reach a termination state before resetting",
    )

    # Orchestrated session fields
    protocol_stack_config: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Protocol stack configuration from plugin",
    )
    current_stage: str = Field(
        default="default",
        description="Current protocol stage name",
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Persisted ProtocolContext snapshot for session resume",
    )

    # Connection state
    connection_mode: str = Field(
        default="per_test",
        description="Connection lifecycle: per_test, per_stage, or session",
    )
    connection_id: Optional[str] = Field(
        default=None,
        description="Active connection identifier",
    )
    reconnect_count: int = Field(
        default=0,
        description="Number of reconnections during this session",
    )

    # Heartbeat state
    heartbeat_enabled: bool = Field(
        default=False,
        description="Whether heartbeat is active",
    )
    heartbeat_last_sent: Optional[datetime] = Field(
        default=None,
        description="Timestamp of last heartbeat sent",
    )
    heartbeat_last_ack: Optional[datetime] = Field(
        default=None,
        description="Timestamp of last heartbeat acknowledgment",
    )
    heartbeat_failures: int = Field(
        default=0,
        description="Consecutive heartbeat failures",
    )

    # Field mutation tracking
    field_mutation_counts: Dict[str, int] = Field(
        default_factory=dict, description="Per-field mutation counts: {field_name: count}"
    )

    # Computed properties
    @property
    def coverage_percentage(self) -> float:
        """Returns % of states visited vs total in protocol"""
        if not self.state_coverage:
            return 0.0
        total_states = len(self.state_coverage)
        if total_states == 0:
            return 0.0
        visited = sum(1 for count in self.state_coverage.values() if count > 0)
        return (visited / total_states) * 100.0

    @property
    def unexplored_states(self) -> List[str]:
        """States defined in protocol but never reached"""
        return [state for state, count in self.state_coverage.items() if count == 0]


class MutationStrategy(BaseModel):
    """Mutation configuration"""

    bitflip: bool = True
    byte_flip: bool = True
    arithmetic: bool = True
    interesting_values: bool = True
    havoc: bool = True
    splice: bool = False


class FuzzConfig(BaseModel):
    """Fuzzing run configuration"""

    protocol: str
    target_host: str
    target_port: int
    transport: Optional[TransportProtocol] = Field(
        default=None,
        description="Override protocol's default transport (tcp/udp)",
    )
    mutation_strategy: MutationStrategy = Field(default_factory=MutationStrategy)
    enabled_mutators: Optional[List[str]] = Field(
        default=None, description="Explicit mutators to use (overrides strategy flags)"
    )
    execution_mode: ExecutionMode = Field(default=ExecutionMode.CORE)
    max_iterations: Optional[int] = None
    timeout_per_test_ms: int = 5000
    rate_limit_per_second: Optional[int] = Field(
        default=None, description="Maximum test cases per second (None = unlimited)"
    )
    mutation_mode: Optional[str] = Field(
        default=None, description="Mutation mode: structure_aware, byte_level, or hybrid"
    )
    structure_aware_weight: Optional[int] = Field(
        default=None, description="Percentage for structure-aware mutations in hybrid mode (0-100)"
    )
    enable_state_tracking: bool = True

    # NEW: Targeting configuration
    target_state: Optional[str] = Field(
        default=None, description="Focus fuzzing on specific state (for stateful protocols)"
    )
    fuzzing_mode: str = Field(
        default="random", description="Fuzzing strategy: random, breadth_first, depth_first, targeted"
    )
    mutable_fields: Optional[List[str]] = Field(
        default=None, description="Restrict mutations to specific fields (None = all mutable fields)"
    )
    field_mutation_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Per-field mutation configuration {field_name: {mutators: [...], weight: 0.8}}"
    )

    # Session lifecycle options
    session_reset_interval: Optional[int] = Field(
        default=None, description="Reset protocol state every N test cases (None = use mode default)"
    )
    enable_termination_fuzzing: bool = Field(
        default=False, description="Periodically inject termination state transitions to test cleanup code"
    )


class AgentWorkItem(BaseModel):
    """Serialized task sent to an agent"""

    session_id: str
    test_case_id: str
    protocol: str
    target_host: str
    target_port: int
    transport: TransportProtocol = TransportProtocol.TCP
    data: bytes
    timeout_ms: int


class AgentTestResult(BaseModel):
    """Result payload submitted by an agent"""

    session_id: str
    test_case_id: str
    result: TestCaseResult
    execution_time_ms: float
    cpu_usage: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    crashed: bool = False
    hung: bool = False
    response: Optional[bytes] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OneOffTestRequest(BaseModel):
    """Ad-hoc test case execution request"""

    protocol: str
    target_host: str
    target_port: int
    payload: bytes
    execution_mode: ExecutionMode = ExecutionMode.CORE
    timeout_ms: int = 5000
    mutators: Optional[List[str]] = None  # Allows reusing existing seeds for chaining
    transport: Optional[TransportProtocol] = Field(
        default=None,
        description="Override protocol-defined transport for this request",
    )


class OneOffTestResult(BaseModel):
    """Response for an ad-hoc test"""

    success: bool
    result: TestCaseResult
    execution_time_ms: float
    response: Optional[bytes] = None
    crash_report_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PreviewField(BaseModel):
    """Field information in a test case preview"""

    name: str
    value: Any
    hex: str
    type: str
    mutable: bool = True
    computed: bool = False
    references: Optional[Union[str, List[str]]] = None
    mutated: bool = False


class TestCasePreview(BaseModel):
    """Preview of a generated test case"""

    id: int
    mode: str  # "baseline" | "mutated"
    mutation_type: Optional[str] = None  # "structure_aware" | "byte_level"
    mutators_used: List[str] = Field(default_factory=list)  # List of mutator names
    focus_field: Optional[str] = None
    hex_dump: str
    total_bytes: int
    fields: List[PreviewField]
    description: Optional[str] = None  # Human-readable description of what was mutated
    # State machine info
    message_type: Optional[str] = None  # Message type (e.g., "CONNECT", "DATA")
    valid_in_state: Optional[str] = None  # State where this message is valid
    causes_transition: Optional[str] = None  # Transition this message causes (e.g., "INIT->CONNECTED")


class PreviewRequest(BaseModel):
    """Request for test case previews"""

    mode: str = "mutations"  # "seeds" | "mutations" | "field_focus"
    count: int = Field(default=3, ge=1, le=10)
    focus_field: Optional[str] = None


class StateTransition(BaseModel):
    """State machine transition definition"""

    from_state: str = Field(alias="from")
    to_state: str = Field(alias="to")
    message_type: Optional[str] = None
    trigger: Optional[str] = None
    expected_response: Optional[str] = None


class StateMachineInfo(BaseModel):
    """State machine metadata for protocol"""

    has_state_model: bool
    initial_state: Optional[str] = None
    states: List[str] = Field(default_factory=list)
    transitions: List[StateTransition] = Field(default_factory=list)
    message_type_to_command: Dict[str, int] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    """Response containing test case previews"""

    protocol: str
    previews: List[TestCasePreview]
    state_machine: Optional[StateMachineInfo] = None


class TestCaseExecutionRecord(BaseModel):
    """Detailed execution record for correlation and replay"""

    test_case_id: str
    session_id: str
    sequence_number: int  # Monotonic counter within session
    timestamp_sent: datetime
    timestamp_response: Optional[datetime] = None
    duration_ms: float

    # Payload information
    payload_size: int
    payload_hash: str  # SHA256 for deduplication
    payload_preview: str  # First 64 bytes in hex for display

    # Protocol information
    protocol: str
    message_type: Optional[str] = None  # From stateful fuzzer
    state_at_send: Optional[str] = None  # Protocol state when sent

    # Execution results
    result: TestCaseResult
    response_size: Optional[int] = None
    response_preview: Optional[str] = None  # First 64 bytes of response in hex
    error_message: Optional[str] = None
    raw_response_b64: Optional[str] = None

    # For replay - base64 encoded
    raw_payload_b64: str  # Base64 encoded payload for JSON transport
    mutation_strategy: Optional[str] = None
    mutators_applied: List[str] = Field(default_factory=list)

    # Orchestrated session fields for replay
    stage_name: Optional[str] = Field(
        default=None,
        description="Protocol stage name (bootstrap, application, etc.)",
    )
    context_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="ProtocolContext snapshot at execution time for replay",
    )
    connection_sequence: int = Field(
        default=0,
        description="Position within current connection (for connection-aware replay)",
    )
    parsed_fields: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Parsed field values for re-serialization during replay",
    )


class ProtocolStageStatus(BaseModel):
    """Runtime status for a protocol stage in orchestrated sessions"""

    name: str
    role: str  # "bootstrap", "fuzz_target", or "teardown"
    status: str = "pending"  # "pending", "active", "complete", "failed"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    exports_captured: Dict[str, bool] = Field(
        default_factory=dict,
        description="Which exports succeeded: {context_key: True/False}",
    )
    error_message: Optional[str] = None


class ExecutionHistoryResponse(BaseModel):
    """Response containing execution history"""

    session_id: str
    total_count: int  # Total executions in session
    returned_count: int  # Number returned in this response
    executions: List[TestCaseExecutionRecord]


class ReplayRequest(BaseModel):
    """Request to replay a test case"""

    sequence_numbers: List[int] = Field(description="Sequence numbers to replay")
    delay_ms: int = Field(default=0, description="Delay between replays in milliseconds")


class ReplayResponse(BaseModel):
    """Response from replay operation"""

    replayed_count: int
    results: List[TestCaseExecutionRecord]


# Protocol Development Tools Models


class ParsedFieldInfo(BaseModel):
    """Information about a parsed field"""

    name: str
    value: Any
    type: str
    offset: int
    size: int
    mutable: bool = True
    description: Optional[str] = None
    hex_value: str


class ParseRequest(BaseModel):
    """Request to parse a packet"""

    protocol: str
    hex_data: str  # Hex string (with or without spaces)


class ParseResponse(BaseModel):
    """Response from packet parsing"""

    success: bool
    fields: List[ParsedFieldInfo] = Field(default_factory=list)
    raw_hex: str
    total_bytes: int
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class ValidationIssue(BaseModel):
    """A single validation issue"""

    severity: str  # "error" | "warning" | "info"
    category: str  # "syntax" | "model" | "seed" | "state"
    message: str
    line: Optional[int] = None
    field: Optional[str] = None


class ValidationRequest(BaseModel):
    """Request to validate plugin code"""

    plugin_code: str


class ValidationResult(BaseModel):
    """Result of plugin validation"""

    valid: bool
    plugin_name: Optional[str] = None
    issues: List[ValidationIssue] = Field(default_factory=list)
    summary: str


# ==============================================================================
# State Machine Walker Models
# ==============================================================================


class WalkerInitRequest(BaseModel):
    """Request to initialize a state walker session"""
    protocol: str


class TransitionInfo(BaseModel):
    """Information about a state transition"""
    from_state: str = Field(alias="from")
    to_state: str = Field(alias="to")
    message_type: Optional[str] = None
    expected_response: Optional[str] = None

    class Config:
        populate_by_name = True


class WalkerExecutionRecord(BaseModel):
    """Record of a single transition execution"""
    execution_number: int
    success: bool
    old_state: str
    new_state: str
    message_type: str
    sent_hex: str
    sent_bytes: int
    sent_parsed: Optional[Dict[str, Any]] = None
    response_hex: Optional[str] = None
    response_bytes: int
    response_parsed: Optional[Dict[str, Any]] = None
    duration_ms: float
    error: Optional[str] = None
    validation_passed: Optional[bool] = None
    validation_error: Optional[str] = None
    timestamp: str


class WalkerStateResponse(BaseModel):
    """Current state of the walker session"""
    session_id: str
    current_state: str
    valid_transitions: List[TransitionInfo]
    state_history: List[str]
    transition_history: List[str]
    state_coverage: Dict[str, int]
    transition_coverage: Dict[str, int]
    execution_history: List[WalkerExecutionRecord] = Field(default_factory=list)


class WalkerExecuteRequest(BaseModel):
    """Request to execute a transition"""
    session_id: str
    transition_index: int  # Index into valid_transitions array
    target_host: str = "target"
    target_port: int = 9999


class WalkerExecuteResponse(BaseModel):
    """Result of executing a transition"""
    success: bool
    old_state: str
    new_state: str
    message_type: str
    sent_hex: str
    sent_bytes: int
    sent_parsed: Optional[Dict[str, Any]] = None
    response_hex: Optional[str] = None
    response_bytes: int
    response_parsed: Optional[Dict[str, Any]] = None
    duration_ms: float
    error: Optional[str] = None
    validation_passed: Optional[bool] = None
    validation_error: Optional[str] = None
    current_state: WalkerStateResponse


# Orchestration API Models


class ContextValueResponse(BaseModel):
    """Response containing a single context value."""
    key: str
    value: Any
    value_type: str


class ContextSnapshotResponse(BaseModel):
    """Response containing full context snapshot."""
    session_id: str
    values: Dict[str, Any]
    bootstrap_complete: bool
    key_count: int


class ContextSetRequest(BaseModel):
    """Request to set a context value."""
    key: str
    value: Any = Field(description="Value to set (string, number, or hex-encoded bytes)")


class StageInfo(BaseModel):
    """Information about a protocol stage."""
    name: str
    role: str  # bootstrap, fuzz_target, teardown
    status: str  # pending, completed, failed, skipped
    attempts: int = 0
    last_error: Optional[str] = None


class StageListResponse(BaseModel):
    """Response listing protocol stages."""
    session_id: str
    stages: List[StageInfo]
    bootstrap_complete: bool


class ConnectionInfo(BaseModel):
    """Information about a managed connection."""
    connection_id: str
    connected: bool
    healthy: bool
    bytes_sent: int
    bytes_received: int
    send_count: int
    recv_count: int
    reconnect_count: int
    created_at: Optional[datetime] = None
    last_send: Optional[datetime] = None
    last_recv: Optional[datetime] = None


class ConnectionStatusResponse(BaseModel):
    """Response with connection status."""
    session_id: str
    connection_mode: str  # per_test, per_stage, session
    active_connections: List[ConnectionInfo]


class HeartbeatStatusResponse(BaseModel):
    """Response with heartbeat status."""
    session_id: str
    enabled: bool
    status: Optional[str] = None  # healthy, warning, failed, disabled, stopped
    interval_ms: Optional[int] = None
    total_sent: int = 0
    failures: int = 0
    last_sent: Optional[datetime] = None
    last_ack: Optional[datetime] = None


class OrchestratedReplayRequest(BaseModel):
    """Request for orchestrated replay with context reconstruction."""
    target_sequence: int = Field(description="Replay executions 1 through this sequence number")
    mode: str = Field(default="stored", description="Replay mode: fresh, stored, or skip")
    delay_ms: int = Field(default=0, description="Delay between replayed messages in ms")
    stop_on_error: bool = Field(default=False, description="Stop replay on first error")


class OrchestratedReplayResult(BaseModel):
    """Result of replaying a single execution."""
    original_sequence: int
    status: str  # success, timeout, error
    response_preview: Optional[str] = None  # First 100 bytes as hex
    error: Optional[str] = None
    duration_ms: float = 0.0
    matched_original: bool = False


class OrchestratedReplayResponse(BaseModel):
    """Response from orchestrated replay operation."""
    session_id: str
    replayed_count: int
    skipped_count: int = 0
    results: List[OrchestratedReplayResult]
    context_after: Dict[str, Any]
    warnings: List[str]
    duration_ms: float
