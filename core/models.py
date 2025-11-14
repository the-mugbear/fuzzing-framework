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
    cpu_usage: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    severity: str = "unknown"


class AgentStatus(BaseModel):
    """Agent health and status"""

    agent_id: str
    hostname: str
    target_host: str
    target_port: int
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


class AgentWorkItem(BaseModel):
    """Serialized task sent to an agent"""

    session_id: str
    test_case_id: str
    protocol: str
    target_host: str
    target_port: int
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

    # For replay - base64 encoded
    raw_payload_b64: str  # Base64 encoded payload for JSON transport


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
    message_type: str
    expected_response: Optional[str] = None

    class Config:
        populate_by_name = True


class WalkerStateResponse(BaseModel):
    """Current state of the walker session"""
    session_id: str
    current_state: str
    valid_transitions: List[TransitionInfo]
    state_history: List[str]
    transition_history: List[str]
    state_coverage: Dict[str, int]
    transition_coverage: Dict[str, int]


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
    response_hex: Optional[str] = None
    response_bytes: int
    duration_ms: float
    error: Optional[str] = None
    current_state: WalkerStateResponse
