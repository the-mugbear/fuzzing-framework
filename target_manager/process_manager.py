"""Process Manager — spawns, monitors, and stops target server processes."""
from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, Optional, Set

from target_manager.models import (
    HealthStatus,
    LogResponse,
    RunningTarget,
    ServerMeta,
    TransportType,
)

logger = logging.getLogger("target_manager.process_manager")

MAX_LOG_LINES = 2000
HEALTH_CHECK_INTERVAL = 5.0  # seconds
STARTUP_GRACE_PERIOD = 2.0  # seconds before first health check


class TargetProcess:
    """Wraps an asyncio subprocess with log capture and health tracking."""

    def __init__(
        self,
        target_id: str,
        meta: ServerMeta,
        host: str,
        port: int,
        process: asyncio.subprocess.Process,
    ):
        self.id = target_id
        self.meta = meta
        self.host = host
        self.port = port
        self.process = process
        self.started_at = datetime.now(timezone.utc)
        self.health = HealthStatus.STARTING
        self.last_health_check: Optional[datetime] = None
        self.logs: Deque[str] = deque(maxlen=MAX_LOG_LINES)
        self._log_tasks: list[asyncio.Task] = []

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid

    @property
    def is_alive(self) -> bool:
        return self.process.returncode is None

    def to_running_target(self) -> RunningTarget:
        return RunningTarget(
            id=self.id,
            script=self.meta.script,
            name=self.meta.name,
            transport=self.meta.transport,
            host=self.host,
            port=self.port,
            pid=self.pid,
            health=self.health,
            started_at=self.started_at,
            last_health_check=self.last_health_check,
            log_lines=len(self.logs),
            compatible_plugins=self.meta.compatible_plugins,
        )

    def get_logs(self, tail: int = 200) -> LogResponse:
        lines = list(self.logs)
        if tail and tail < len(lines):
            lines = lines[-tail:]
        return LogResponse(target_id=self.id, lines=lines, total_lines=len(self.logs))

    async def start_log_capture(self):
        """Start background tasks to read stdout/stderr."""
        if self.process.stdout:
            self._log_tasks.append(
                asyncio.create_task(self._read_stream(self.process.stdout, "stdout"))
            )
        if self.process.stderr:
            self._log_tasks.append(
                asyncio.create_task(self._read_stream(self.process.stderr, "stderr"))
            )

    async def _read_stream(self, stream: asyncio.StreamReader, label: str):
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                self.logs.append(f"[{label}] {decoded}")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.logs.append(f"[{label}] <read error: {exc}>")

    async def stop(self):
        """Terminate the process gracefully."""
        for task in self._log_tasks:
            task.cancel()
        if self.is_alive:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.health = HealthStatus.UNHEALTHY


class ProcessManager:
    """Manages the lifecycle of target server processes."""

    def __init__(self, tests_dir: Path, port_range: tuple[int, int] = (9990, 9999)):
        self.tests_dir = tests_dir
        self.port_range = port_range
        self._targets: Dict[str, TargetProcess] = {}
        self._used_ports: Set[int] = set()
        self._health_task: Optional[asyncio.Task] = None

    @property
    def running_targets(self) -> Dict[str, TargetProcess]:
        return dict(self._targets)

    def _allocate_port(self, requested: int = 0) -> int:
        """Allocate a port from the pool."""
        if requested > 0:
            if requested in self._used_ports:
                raise ValueError(f"Port {requested} already in use by another target")
            self._used_ports.add(requested)
            return requested

        low, high = self.port_range
        for port in range(low, high + 1):
            if port not in self._used_ports:
                self._used_ports.add(port)
                return port
        raise ValueError(f"No free ports in range {low}-{high}")

    def _release_port(self, port: int):
        self._used_ports.discard(port)

    def find_by_port(self, port: int) -> Optional[TargetProcess]:
        for tp in self._targets.values():
            if tp.port == port:
                return tp
        return None

    async def start_target(
        self, meta: ServerMeta, host: str = "0.0.0.0", port: int = 0
    ) -> TargetProcess:
        """Spawn a new target server process."""
        actual_port = self._allocate_port(port or meta.default_port)
        target_id = uuid.uuid4().hex[:12]

        script_path = self.tests_dir / meta.script
        if not script_path.exists():
            self._release_port(actual_port)
            raise FileNotFoundError(f"Server script not found: {script_path}")

        cmd = [
            "python", str(script_path),
            "--host", host,
            "--port", str(actual_port),
        ]

        logger.info(
            "starting_target",
            extra={"id": target_id, "script": meta.script, "port": actual_port},
        )

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.tests_dir.parent),  # project root
        )

        tp = TargetProcess(target_id, meta, host, actual_port, process)
        await tp.start_log_capture()
        self._targets[target_id] = tp

        logger.info(
            "target_started",
            extra={"id": target_id, "pid": tp.pid, "port": actual_port},
        )
        return tp

    async def stop_target(self, target_id: str) -> bool:
        """Stop a running target by ID."""
        tp = self._targets.pop(target_id, None)
        if tp is None:
            return False

        await tp.stop()
        self._release_port(tp.port)
        logger.info("target_stopped", extra={"id": target_id, "port": tp.port})
        return True

    async def stop_all(self):
        """Stop all running targets."""
        ids = list(self._targets.keys())
        for tid in ids:
            await self.stop_target(tid)

    def get_target(self, target_id: str) -> Optional[TargetProcess]:
        return self._targets.get(target_id)

    async def start_health_checks(self):
        """Start periodic health checking."""
        if self._health_task is None or self._health_task.done():
            self._health_task = asyncio.create_task(self._health_loop())

    async def _health_loop(self):
        """Periodically probe all running targets."""
        while True:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            for tp in list(self._targets.values()):
                if not tp.is_alive:
                    tp.health = HealthStatus.UNHEALTHY
                    continue

                # Skip health check during startup grace period
                elapsed = (datetime.now(timezone.utc) - tp.started_at).total_seconds()
                if elapsed < STARTUP_GRACE_PERIOD:
                    continue

                tp.health = await self._probe_health(tp)
                tp.last_health_check = datetime.now(timezone.utc)

    async def _probe_health(self, tp: TargetProcess) -> HealthStatus:
        """Check if a target server is accepting connections."""
        try:
            if tp.meta.transport == TransportType.UDP:
                return await self._probe_udp(tp.host, tp.port)
            else:
                return await self._probe_tcp(tp.host, tp.port)
        except Exception:
            return HealthStatus.UNHEALTHY

    async def _probe_tcp(self, host: str, port: int) -> HealthStatus:
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        try:
            await loop.run_in_executor(None, sock.connect, ("127.0.0.1", port))
            return HealthStatus.HEALTHY
        except (ConnectionRefusedError, OSError, TimeoutError):
            return HealthStatus.UNHEALTHY
        finally:
            sock.close()

    async def _probe_udp(self, host: str, port: int) -> HealthStatus:
        """UDP health check — bind succeeds means port is busy (good)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("127.0.0.1", port))
            # If we can bind, nothing is listening
            return HealthStatus.UNHEALTHY
        except OSError:
            # Can't bind → something is listening → healthy
            return HealthStatus.HEALTHY
        finally:
            sock.close()

    async def shutdown(self):
        """Graceful shutdown — stop health checks and all targets."""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        await self.stop_all()
