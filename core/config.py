"""
Core Configuration Management - Centralized settings for the fuzzer.

This module provides configuration management using Pydantic settings,
supporting environment variables and sensible defaults.

Component Overview:
-------------------
The Settings class defines all configurable parameters for:
- API server configuration
- Security settings (TLS, auth tokens)
- Path configuration (plugins, corpus, logs)
- Fuzzing engine parameters
- Transport settings
- Session management
- Mutation strategies
- Stateful fuzzing behavior

Configuration Sources:
---------------------
Settings are loaded in this priority order (highest first):
1. Environment variables (FUZZER_<SETTING_NAME>)
2. .env file in project root
3. Default values in this module

Key Setting Categories:
----------------------
1. API Settings:
   - api_host, api_port: Server binding
   - cors_enabled, cors_origins: CORS configuration

2. Security:
   - tls_cert_path, tls_key_path: HTTPS configuration
   - agent_auth_token: Agent authentication

3. Paths:
   - plugins_dir: Protocol plugin location
   - corpus_dir: Seed and finding storage
   - crash_dir: Crash data storage
   - log_dir: Log file location

4. Fuzzing Engine:
   - max_mutations_per_seed: Mutation count limit
   - max_concurrent_tests: Parallelism limit
   - checkpoint_frequency: State save interval

5. Mutation Strategy:
   - mutation_mode: "structure_aware", "byte_level", "hybrid"
   - structure_aware_weight: Balance between strategies
   - havoc_max_size: Maximum mutation expansion

6. Stateful Fuzzing:
   - stateful_reset_interval_*: Mode-specific reset intervals
   - termination_test_window: Tests before reset for termination
   - termination_test_interval: Periodic termination injection

Usage Example:
-------------
    from core.config import settings

    # Access settings
    print(f"API port: {settings.api_port}")
    print(f"Corpus dir: {settings.corpus_dir}")

    # Settings are read-only after initialization
    # To change, set environment variables before import

Environment Variables:
---------------------
All settings can be overridden with FUZZER_ prefix:
- FUZZER_API_PORT=9000
- FUZZER_CORPUS_DIR=/data/corpus
- FUZZER_MAX_CONCURRENT_SESSIONS=3

See Also:
--------
- docker-compose.yml - Container environment configuration
- CLAUDE.md - Environment variable documentation
- docs/QUICKSTART.md - Configuration guide
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
    # Modes: "byte_level", "structure_aware", "hybrid" (random mutations)
    #        "enumeration", "enumeration_pairwise", "enumeration_full" (systematic)
    mutation_mode: str = "hybrid"
    structure_aware_weight: int = 70  # Percentage for structure-aware (0-100)
    fallback_on_parse_error: bool = True  # Fall back to byte-level if parsing fails

    # Structure-aware mutation
    havoc_expansion_min: float = 1.5  # Minimum expansion factor for havoc mutations
    havoc_expansion_max: float = 3.0  # Maximum expansion factor for havoc mutations
    havoc_max_size: int = 4096  # Maximum size for havoc mutations

    # Corpus cache
    seed_cache_max_size: int = 1000  # Maximum seeds to keep in memory cache

    # Stateful fuzzing
    stateful_progression_weight: float = 0.8  # Weight for state progression (0.0-1.0)
    stateful_reset_interval_bfs: int = 20  # Reset interval for breadth-first strategy
    stateful_reset_interval_dfs: int = 500  # Reset interval for depth-first strategy
    stateful_reset_interval_targeted: int = 100  # Reset interval for targeted strategy
    stateful_reset_interval_random: int = 300  # Reset interval for random walk strategy

    # Termination fuzzing
    termination_test_window: int = 3  # Number of tests before reset to try termination
    termination_test_interval: int = 50  # Periodic termination injection interval

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
