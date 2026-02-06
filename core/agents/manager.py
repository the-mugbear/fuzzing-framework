"""
Agent Manager - Coordinates remote agents and work distribution.

This module manages the lifecycle and work distribution for remote fuzzing
agents that execute test cases near target systems.

Component Overview:
-------------------
The AgentManager provides centralized coordination for:
- Agent registration and heartbeat tracking
- Work queue management per target endpoint
- Test case dispatch and completion tracking
- Session cleanup when fuzzing stops

Key Responsibilities:
--------------------
1. Agent Registration:
   - Track registered agents by ID
   - Associate agents with target endpoints
   - Monitor agent health via heartbeats

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
    agent_manager.register_agent(
        agent_id="agent-1",
        hostname="worker-node",
        target_host="target-server",
        target_port=9999,
        transport=TransportProtocol.TCP,
    )

    # Dispatch work
    await agent_manager.enqueue_test_case(
        target_host="target-server",
        target_port=9999,
        transport=TransportProtocol.TCP,
        work=work_item,
    )

    # Cleanup
    await agent_manager.clear_session(session_id)

Configuration:
-------------
- agent_queue_size: Maximum items per queue (from settings)

See Also:
--------
- core/engine/agent_dispatcher.py - High-level dispatch coordination
- core/models.py - AgentStatus, AgentWorkItem definitions
- docs/developer/05_agent_and_core_communication.md - Architecture docs
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional, Tuple

import structlog

from core.config import settings
from core.models import AgentStatus, AgentWorkItem, TransportProtocol

logger = structlog.get_logger()

TargetKey = Tuple[str, int, TransportProtocol]


class AgentManager:
    """Coordinates remote agents and work distribution"""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentStatus] = {}
        self._queues: Dict[TargetKey, asyncio.Queue[AgentWorkItem]] = defaultdict(
            lambda: asyncio.Queue(maxsize=settings.agent_queue_size)
        )
        self._inflight: Dict[str, Tuple[str, str]] = {}  # test_case_id -> (agent_id, session_id)
        self._lock = asyncio.Lock()

    def register_agent(
        self,
        agent_id: str,
        hostname: str,
        target_host: str,
        target_port: int,
        transport: TransportProtocol,
    ) -> AgentStatus:
        """Register or update an agent record"""
        status = AgentStatus(
            agent_id=agent_id,
            hostname=hostname,
            target_host=target_host,
            target_port=target_port,
            is_alive=True,
            last_heartbeat=datetime.utcnow(),
            transport=transport,
        )
        self._agents[agent_id] = status
        logger.info(
            "agent_registered",
            agent_id=agent_id,
            target_host=target_host,
            target_port=target_port,
            transport=transport.value,
        )
        return status

    def heartbeat(
        self,
        agent_id: str,
        cpu_usage: float = 0.0,
        memory_usage_mb: float = 0.0,
        active_tests: int = 0,
    ) -> Optional[AgentStatus]:
        """Update heartbeat info for an agent"""
        status = self._agents.get(agent_id)
        if not status:
            logger.warning("heartbeat_from_unknown_agent", agent_id=agent_id)
            return None

        status.is_alive = True
        status.last_heartbeat = datetime.utcnow()
        status.cpu_usage = cpu_usage
        status.memory_usage_mb = memory_usage_mb
        status.active_test_count = active_tests
        return status

    def get_agent(self, agent_id: str) -> Optional[AgentStatus]:
        return self._agents.get(agent_id)

    def has_agent_for_target(
        self,
        target_host: str,
        target_port: int,
        transport: TransportProtocol,
    ) -> bool:
        """Check if at least one agent is registered for the target"""
        for status in self._agents.values():
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
        work: AgentWorkItem,
    ) -> None:
        """Queue a test case for agents matching the given target"""
        key = (target_host, target_port, transport)
        queue = self._queues[key]
        await queue.put(work)
        logger.debug(
            "agent_task_enqueued",
            session_id=work.session_id,
            test_case_id=work.test_case_id,
            target_host=target_host,
            target_port=target_port,
            transport=transport.value,
        )

    async def request_work(self, agent_id: str, timeout: float = 0.5) -> Optional[AgentWorkItem]:
        """Return the next work item for an agent if available"""
        agent = self._agents.get(agent_id)
        if not agent:
            logger.warning("request_from_unknown_agent", agent_id=agent_id)
            return None

        queue = self._queues[(agent.target_host, agent.target_port, agent.transport)]
        try:
            work = await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        async with self._lock:
            self._inflight[work.test_case_id] = (agent_id, work.session_id)

        logger.debug(
            "agent_task_assigned",
            agent_id=agent_id,
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
                retained: list[AgentWorkItem] = []
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
                for test_case_id, (_agent_id, sess_id) in self._inflight.items()
                if sess_id == session_id
            ]
            for test_case_id in to_remove:
                self._inflight.pop(test_case_id, None)

        logger.info("agent_tasks_cleared", session_id=session_id)


agent_manager = AgentManager()
