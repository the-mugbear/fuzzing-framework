"""Pydantic models for the Target Manager service."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TransportType(str, Enum):
    TCP = "tcp"
    UDP = "udp"


class HealthStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"


class ServerMeta(BaseModel):
    """Metadata about an available test server script."""

    script: str = Field(description="Filename relative to tests/")
    name: str = Field(description="Human-readable short name")
    description: str = Field(default="", description="What this server does")
    transport: TransportType = TransportType.TCP
    default_port: int = Field(default=9999, ge=1, le=65535)
    compatible_plugins: List[str] = Field(
        default_factory=list,
        description="Plugin names this server is designed to exercise",
    )
    vulnerabilities: int = Field(
        default=0, description="Number of intentional vulns (for training servers)"
    )


class RunningTarget(BaseModel):
    """A currently running target server process."""

    id: str = Field(description="Unique target instance ID")
    script: str
    name: str
    transport: TransportType
    host: str = "0.0.0.0"
    port: int = Field(ge=1, le=65535)
    pid: Optional[int] = None
    health: HealthStatus = HealthStatus.STARTING
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_health_check: Optional[datetime] = None
    log_lines: int = 0
    compatible_plugins: List[str] = Field(default_factory=list)


class StartTargetRequest(BaseModel):
    """Request to start a target server."""

    script: str = Field(description="Server script filename (e.g. 'feature_reference_server.py')")
    port: int = Field(default=0, ge=0, le=65535, description="Port (0 = use default)")
    host: str = Field(default="0.0.0.0")


class TargetManagerHealth(BaseModel):
    """Target manager overall health."""

    status: str = "healthy"
    running_targets: int = 0
    available_servers: int = 0
    port_pool_available: int = 0


class LogResponse(BaseModel):
    """Log output from a target server."""

    target_id: str
    lines: List[str] = Field(default_factory=list)
    total_lines: int = 0
