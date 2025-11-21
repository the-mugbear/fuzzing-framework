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

    # Mutation strategy
    mutation_mode: str = "hybrid"  # "structure_aware", "byte_level", "hybrid"
    structure_aware_weight: int = 70  # Percentage for structure-aware (0-100)
    fallback_on_parse_error: bool = True  # Fall back to byte-level if parsing fails

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
