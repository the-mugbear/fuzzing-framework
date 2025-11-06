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
    is_alive: bool
    last_heartbeat: datetime
    cpu_usage: float
    memory_usage_mb: float
    active_test_count: int = 0


class FuzzSession(BaseModel):
    """Fuzzing session configuration and state"""

    model_config = {"ser_json_inf_nan": "constants"}

    id: str
    protocol: str
    status: FuzzSessionStatus = FuzzSessionStatus.IDLE
    target_host: str
    target_port: int
    seed_corpus: List[str] = Field(default_factory=list)
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
    max_iterations: Optional[int] = None
    timeout_per_test_ms: int = 5000
    enable_state_tracking: bool = True
