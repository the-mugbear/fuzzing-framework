"""
Core configuration management
"""
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Core fuzzer settings"""

    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Security
    tls_cert_path: Optional[Path] = None
    tls_key_path: Optional[Path] = None
    agent_auth_token: Optional[str] = None

    # CORS - permissive by default since this is a local tool
    # If you expose this to a network, restrict cors_origins to specific domains
    cors_enabled: bool = True
    cors_origins: list[str] = ["*"]  # Allow all origins for local development
    # To restrict: set FUZZER_CORS_ORIGINS='["http://localhost:3000"]'

    # Paths
    project_root: Path = Path(__file__).parent.parent
    plugins_dir: Path = project_root / "core" / "plugins"
    corpus_dir: Path = project_root / "core" / "corpus"
    crash_dir: Path = project_root / "core" / "crashes"
    log_dir: Path = project_root / "logs"

    # Fuzzing engine
    max_mutations_per_seed: int = 1000
    mutation_timeout_sec: int = 5
    max_concurrent_tests: int = 10
    max_response_bytes: int = 1024 * 1024

    # Session persistence
    checkpoint_frequency: int = 1000  # Save session state every N test cases
    default_history_limit: int = 100  # Keep last N execution records in memory

    # Transport settings
    tcp_buffer_size: int = 4096  # Read buffer size for TCP responses
    udp_buffer_size: int = 4096  # Read buffer size for UDP responses

    # Session concurrency
    max_concurrent_sessions: int = 1  # Default: single session for stability
    # Set to higher value (2-5) only if you have sufficient resources
    # Consider: CPU cores, RAM (500MB-2GB per session), network bandwidth

    # Mutation strategy
    mutation_mode: str = "hybrid"  # "structure_aware", "byte_level", "hybrid"
    structure_aware_weight: int = 70  # Percentage for structure-aware (0-100)
    fallback_on_parse_error: bool = True  # Fall back to byte-level if parsing fails

    # Structure-aware mutation
    havoc_expansion_min: float = 1.5  # Minimum expansion factor for havoc mutations
    havoc_expansion_max: float = 3.0  # Maximum expansion factor for havoc mutations

    # Stateful fuzzing
    stateful_progression_weight: float = 0.8  # Weight for state progression (0.0-1.0)
    stateful_reset_interval_bfs: int = 20  # Reset interval for breadth-first strategy
    stateful_reset_interval_dfs: int = 500  # Reset interval for depth-first strategy
    stateful_reset_interval_targeted: int = 100  # Reset interval for targeted strategy
    stateful_reset_interval_random: int = 300  # Reset interval for random walk strategy

    # Agent settings
    agent_heartbeat_interval: int = 30
    agent_timeout_sec: int = 60
    agent_queue_size: int = 1024

    # Oracle thresholds
    cpu_spike_threshold: float = 90.0  # percent
    memory_leak_threshold_mb: int = 100

    class Config:
        env_prefix = "FUZZER_"
        env_file = ".env"


settings = Settings()
