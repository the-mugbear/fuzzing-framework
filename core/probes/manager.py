"""
Probe Manager - Coordinates remote probes and work distribution.

This module manages the lifecycle and work distribution for remote fuzzing
probes that execute test cases near target systems.

Component Overview:
-------------------
The AgentManager provides centralized coordination for:
- Probe registration and heartbeat tracking
- Work queue management per target endpoint
- Test case dispatch and completion tracking
- Session cleanup when fuzzing stops

Key Responsibilities:
--------------------
1. Probe Registration:
   - Track registered probes by ID
   - Associate probes with target endpoints
   - Monitor probe health via heartbeats

2. Work Queue Management:
   - Maintain per-target work queues
   - Size-limited queues prevent memory exhaustion
   - Thread-safe queue operations

3. Test Case Dispatch:
   - Route work items to appropriate target queue
   - Track in-flight test cases
   - Handle work completion notifications

4. Session Cleanup:
   - Clear pending work when sessions stop
   - Use atomic operations to prevent race conditions
   - Clean up in-flight tracking

Thread Safety:
-------------
The AgentManager uses asyncio.Lock for thread-safe operations on:
- Queue manipulation during session cleanup
- In-flight test case tracking

Usage Example:
-------------
    # Registration
    probe_manager.register_probe(
        probe_id="probe-1",
        hostname="worker-node",
        target_host="target-server",
        target_port=9999,
        transport=TransportProtocol.TCP,
    )

    # Dispatch work
    await probe_manager.enqueue_test_case(
        target_host="target-server",
        target_port=9999,
        transport=TransportProtocol.TCP,
        work=work_item,
    )

    # Cleanup
    await probe_manager.clear_session(session_id)

Configuration:
-------------
- probe_queue_size: Maximum items per queue (from settings)

See Also:
--------
- core/engine/probe_dispatcher.py - High-level dispatch coordination
- core/models.py - ProbeStatus, ProbeWorkItem definitions
- docs/developer/05_probe_and_core_communication.md - Architecture docs
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from core import utcnow
from typing import Dict, Optional, Tuple

import structlog

from core.config import settings
from core.models import ProbeStatus, ProbeWorkItem, TransportProtocol

logger = structlog.get_logger()

TargetKey = Tuple[str, int, TransportProtocol]


class AgentManager:
    """Coordinates remote probes and work distribution"""

    def __init__(self) -> None:
        self._probes: Dict[str, ProbeStatus] = {}
        self._queues: Dict[TargetKey, asyncio.Queue[ProbeWorkItem]] = defaultdict(
            lambda: asyncio.Queue(maxsize=settings.probe_queue_size)
        )
        self._inflight: Dict[str, Tuple[str, str]] = {}  # test_case_id -> (probe_id, session_id)
        self._lock = asyncio.Lock()

    def register_probe(
        self,
        probe_id: str,
        hostname: str,
        target_host: str,
        target_port: int,
        transport: TransportProtocol,
    ) -> ProbeStatus:
        """Register or update a probe record"""
        status = ProbeStatus(
            probe_id=probe_id,
            hostname=hostname,
            target_host=target_host,
            target_port=target_port,
            is_alive=True,
            last_heartbeat=utcnow(),
            transport=transport,
        )
        self._probes[probe_id] = status
        logger.info(
            "probe_registered",
            probe_id=probe_id,
            target_host=target_host,
            target_port=target_port,
            transport=transport.value,
        )
        return status

    def heartbeat(
        self,
        probe_id: str,
        cpu_usage: float = 0.0,
        memory_usage_mb: float = 0.0,
        active_tests: int = 0,
    ) -> Optional[ProbeStatus]:
        """Update heartbeat info for a probe"""
        status = self._probes.get(probe_id)
        if not status:
            logger.warning("heartbeat_from_unknown_probe", probe_id=probe_id)
            return None

        status.is_alive = True
        status.last_heartbeat = utcnow()
        status.cpu_usage = cpu_usage
        status.memory_usage_mb = memory_usage_mb
        status.active_test_count = active_tests
        return status

    def get_probe(self, probe_id: str) -> Optional[ProbeStatus]:
        return self._probes.get(probe_id)

    def has_probe_for_target(
        self,
        target_host: str,
        target_port: int,
        transport: TransportProtocol,
    ) -> bool:
        """Check if at least one probe is registered for the target"""
        for status in self._probes.values():
            if (
                status.target_host == target_host
                and status.target_port == target_port
                and status.transport == transport
                and status.is_alive
            ):
                return True
        return False

    async def enqueue_test_case(
        self,
        target_host: str,
        target_port: int,
        transport: TransportProtocol,
        work: ProbeWorkItem,
    ) -> None:
        """Queue a test case for probes matching the given target"""
        key = (target_host, target_port, transport)
        queue = self._queues[key]
        await queue.put(work)
        logger.debug(
            "probe_task_enqueued",
            session_id=work.session_id,
            test_case_id=work.test_case_id,
            target_host=target_host,
            target_port=target_port,
            transport=transport.value,
        )

    async def request_work(self, probe_id: str, timeout: float = 0.5) -> Optional[ProbeWorkItem]:
        """Return the next work item for a probe if available"""
        probe = self._probes.get(probe_id)
        if not probe:
            logger.warning("request_from_unknown_probe", probe_id=probe_id)
            return None

        queue = self._queues[(probe.target_host, probe.target_port, probe.transport)]
        try:
            work = await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        async with self._lock:
            self._inflight[work.test_case_id] = (probe_id, work.session_id)

        logger.debug(
            "probe_task_assigned",
            probe_id=probe_id,
            test_case_id=work.test_case_id,
            session_id=work.session_id,
        )
        return work

    async def complete_work(self, test_case_id: str) -> None:
        """Mark an inflight test case as completed"""
        async with self._lock:
            self._inflight.pop(test_case_id, None)

    async def clear_session(self, session_id: str) -> None:
        """Remove pending tasks for a session from all queues.

        Uses the instance lock to ensure atomic queue manipulation and prevent
        race conditions with concurrent coroutines.
        """
        async with self._lock:
            # Drain and filter each queue atomically
            for queue in self._queues.values():
                retained: list[ProbeWorkItem] = []
                while not queue.empty():
                    try:
                        item = queue.get_nowait()
                    except asyncio.QueueEmpty:  # pragma: no cover - guard
                        break
                    if item.session_id != session_id:
                        retained.append(item)
                for item in retained:
                    queue.put_nowait(item)

            # Clean up inflight tasks (already protected by lock)
            to_remove = [
                test_case_id
                for test_case_id, (_probe_id, sess_id) in self._inflight.items()
                if sess_id == session_id
            ]
            for test_case_id in to_remove:
                self._inflight.pop(test_case_id, None)

        logger.info("probe_tasks_cleared", session_id=session_id)


probe_manager = AgentManager()
