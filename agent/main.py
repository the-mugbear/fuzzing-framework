"""
Target Agent main application

Lightweight agent that:
1. Registers with Core
2. Receives fuzzed test cases
3. Forwards to target
4. Monitors execution
5. Reports results back to Core
"""
import argparse
import asyncio
import base64
import socket
import sys
import uuid
from typing import Optional

import httpx
import psutil
import structlog

from agent.monitor import TargetExecutor
from core.logging import setup_logging
from core.models import TransportProtocol

setup_logging("agent")

logger = structlog.get_logger()


class FuzzerAgent:
    """
    Minimal fuzzing agent

    Connects to Core and executes test cases against a target
    """

    def __init__(
        self,
        core_url: str,
        target_host: str,
        target_port: int,
        agent_id: Optional[str] = None,
        poll_interval: float = 0.5,
        launch_cmd: Optional[str] = None,
        transport: TransportProtocol = TransportProtocol.TCP,
    ):
        self.core_url = core_url.rstrip("/")
        self.target_host = target_host
        self.target_port = target_port
        self.agent_id = agent_id or str(uuid.uuid4())
        self.hostname = socket.gethostname()
        self.transport = transport
        self.executor = TargetExecutor(
            target_host,
            target_port,
            launch_cmd=launch_cmd,
            transport=transport,
        )
        self.poll_interval = poll_interval
        self.launch_cmd = launch_cmd
        self.running = False
        self.active_tests = 0
        self.client: Optional[httpx.AsyncClient] = None
        self._process = psutil.Process()

    async def register(self) -> bool:
        """Register with Core"""
        try:
            response = await self.client.post(
                f"{self.core_url}/api/agents/register",
                json={
                    "agent_id": self.agent_id,
                    "hostname": self.hostname,
                    "target_host": self.target_host,
                    "target_port": self.target_port,
                    "transport": self.transport.value,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("agent_registered", agent_id=self.agent_id, core_url=self.core_url)
            return True
        except Exception as e:
            logger.error("registration_failed", error=str(e), core_url=self.core_url)
            return False

    async def heartbeat_loop(self):
        """Send periodic heartbeats to Core"""
        while self.running:
            try:
                cpu_usage = self._process.cpu_percent(interval=None)
                memory_usage = self._process.memory_info().rss / (1024 * 1024)
                await self.client.post(
                    f"{self.core_url}/api/agents/{self.agent_id}/heartbeat",
                    json={
                        "status": "running",
                        "target_host": self.target_host,
                        "target_port": self.target_port,
                        "cpu_usage": cpu_usage,
                        "memory_usage_mb": memory_usage,
                        "active_tests": self.active_tests,
                        "transport": self.transport.value,
                    },
                    timeout=5.0,
                )
                logger.debug("heartbeat_sent", agent_id=self.agent_id)
            except Exception as e:
                logger.error("heartbeat_failed", error=str(e))

            await asyncio.sleep(30)

    async def work_loop(self):
        """Poll for work and execute test cases"""
        while self.running:
            work_item = await self._fetch_next_case()
            if not work_item:
                await asyncio.sleep(self.poll_interval)
                continue

            await self._handle_work(work_item)

    async def _fetch_next_case(self) -> Optional[dict]:
        try:
            response = await self.client.get(
                f"{self.core_url}/api/agents/{self.agent_id}/next-case",
                timeout=15.0,
            )
            if response.status_code == 204:
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("work_poll_http_error", status=exc.response.status_code)
            return None
        except Exception as exc:
            logger.error("work_poll_failed", error=str(exc))
            return None

    async def _handle_work(self, work_item: dict) -> None:
        try:
            payload = base64.b64decode(work_item["data"])
        except KeyError:
            logger.error("malformed_work_item", work_item=work_item)
            return

        timeout = work_item.get("timeout_ms", 5000) / 1000.0
        transport_value = work_item.get("transport", self.transport.value)
        try:
            work_transport = TransportProtocol(str(transport_value).lower())
        except ValueError:
            logger.warning("unknown_transport", transport=transport_value)
            work_transport = self.transport
        self.active_tests += 1
        try:
            result = await self.executor.execute_test_case(
                payload,
                timeout_sec=timeout,
                transport=work_transport,
            )
        finally:
            self.active_tests = max(0, self.active_tests - 1)

        if work_transport != self.transport:
            logger.debug(
                "agent_transport_override",
                agent_transport=self.transport.value,
                work_transport=work_transport.value,
            )

        await self._submit_result(work_item, result)

    async def _submit_result(self, work_item: dict, result) -> None:
        response_blob = (
            base64.b64encode(result.response).decode("ascii") if result.response else None
        )
        payload = {
            "session_id": work_item["session_id"],
            "test_case_id": work_item["test_case_id"],
            "result": result.verdict,
            "execution_time_ms": result.execution_time_ms,
            "cpu_usage": result.cpu_usage,
            "memory_usage_mb": result.memory_usage_mb,
            "crashed": result.crashed,
            "hung": result.hung,
            "metadata": {"hostname": self.hostname},
        }
        if response_blob:
            payload["response"] = response_blob

        try:
            await self.client.post(
                f"{self.core_url}/api/agents/{self.agent_id}/result",
                json=payload,
                timeout=10.0,
            )
            logger.debug(
                "result_submitted",
                session_id=work_item["session_id"],
                test_case_id=work_item["test_case_id"],
            )
        except Exception as exc:
            logger.error("result_submit_failed", error=str(exc))

    async def run(self):
        """Main agent loop"""
        logger.info(
            "agent_starting",
            agent_id=self.agent_id,
            target=f"{self.target_host}:{self.target_port}",
            transport=self.transport.value,
        )

        self.client = httpx.AsyncClient(timeout=30.0)

        # Register with Core
        if not await self.register():
            logger.error("failed_to_register", core_url=self.core_url)
            await self.client.aclose()
            return

        self.running = True

        # Start heartbeat loop
        heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        worker_task = asyncio.create_task(self.work_loop())

        try:
            logger.info("agent_ready", agent_id=self.agent_id)
            while self.running:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("agent_shutdown_requested")
        finally:
            self.running = False
            heartbeat_task.cancel()
            worker_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            await self.executor.shutdown()
            if self.client:
                await self.client.aclose()

        logger.info("agent_stopped", agent_id=self.agent_id)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Fuzzer Target Agent")
    parser.add_argument(
        "--core-url",
        default="http://localhost:8000",
        help="URL of the Core API server",
    )
    parser.add_argument(
        "--target-host",
        default="localhost",
        help="Target host to fuzz",
    )
    parser.add_argument(
        "--target-port",
        type=int,
        default=9999,
        help="Target port to fuzz",
    )
    parser.add_argument(
        "--agent-id",
        help="Agent ID (auto-generated if not provided)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Polling interval (seconds) when waiting for work",
    )
    parser.add_argument(
        "--launch-cmd",
        help="Optional command to launch and monitor a local target binary",
    )
    parser.add_argument(
        "--transport",
        choices=[TransportProtocol.TCP.value, TransportProtocol.UDP.value],
        default=TransportProtocol.TCP.value,
        help="Transport to use when communicating with the target",
    )

    args = parser.parse_args()

    agent = FuzzerAgent(
        core_url=args.core_url,
        target_host=args.target_host,
        target_port=args.target_port,
        agent_id=args.agent_id,
        poll_interval=args.poll_interval,
        launch_cmd=args.launch_cmd,
        transport=TransportProtocol(args.transport),
    )

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
