"""
Core data models
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
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
    references: Optional[str] = None
    mutated: bool = False


class TestCasePreview(BaseModel):
    """Preview of a generated test case"""

    id: int
    mode: str  # "baseline" | "mutated"
    focus_field: Optional[str] = None
    hex_dump: str
    total_bytes: int
    fields: List[PreviewField]


class PreviewRequest(BaseModel):
    """Request for test case previews"""

    mode: str = "mutations"  # "seeds" | "mutations" | "field_focus"
    count: int = Field(default=3, ge=1, le=10)
    focus_field: Optional[str] = None


class PreviewResponse(BaseModel):
    """Response containing test case previews"""

    protocol: str
    previews: List[TestCasePreview]
