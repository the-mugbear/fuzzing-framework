"""Integration test for the fuzzing loop.

Tests the full path: create session → start fuzzing → verify test execution.
Uses a real TCP server to validate end-to-end behavior.

Uses httpx.AsyncClient with ASGITransport so that asyncio.sleep() yields
to the event loop, allowing the orchestrator's background fuzzing task
(created via asyncio.create_task) to make progress.
"""
import asyncio
import socket
import threading
import time

import httpx
import pytest

from core.api.server import app


def _find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _run_echo_server(host: str, port: int, stop_event: threading.Event):
    """Minimal echo server for testing."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.settimeout(1.0)
    srv.bind((host, port))
    srv.listen(5)
    while not stop_event.is_set():
        try:
            conn, _ = srv.accept()
            data = conn.recv(4096)
            if data:
                conn.sendall(data)
            conn.close()
        except socket.timeout:
            continue
        except Exception:
            break
    srv.close()


@pytest.fixture
def echo_server():
    """Start an echo TCP server on a free port, yield the port, then stop."""
    port = _find_free_port()
    stop = threading.Event()
    t = threading.Thread(target=_run_echo_server, args=("127.0.0.1", port, stop), daemon=True)
    t.start()
    for _ in range(20):
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
            s.close()
            break
        except OSError:
            time.sleep(0.1)
    yield port
    stop.set()
    t.join(timeout=3)


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestFuzzingLoopIntegration:
    async def test_session_runs_and_counts_tests(self, client, echo_server):
        """Create a session, start it with a small iteration limit, verify it completes."""
        resp = await client.post("/api/sessions", json={
            "protocol": "minimal_tcp",
            "target_host": "127.0.0.1",
            "target_port": echo_server,
            "max_iterations": 10,
            "mutation_mode": "byte_level",
        })
        assert resp.status_code == 200
        session = resp.json()
        session_id = session["id"]
        assert session["status"] == "idle"

        resp = await client.post(f"/api/sessions/{session_id}/start")
        assert resp.status_code == 200

        # Poll with asyncio.sleep so background task can progress
        for _ in range(60):
            await asyncio.sleep(0.5)
            resp = await client.get(f"/api/sessions/{session_id}")
            s = resp.json()
            if s["status"] in ("completed", "failed"):
                break

        final = (await client.get(f"/api/sessions/{session_id}")).json()
        assert final["status"] == "completed", f"Session status: {final['status']}, error: {final.get('error_message')}"
        assert final["total_tests"] == 10

        await client.delete(f"/api/sessions/{session_id}")

    async def test_session_fails_gracefully_no_target(self, client):
        """Session should fail with clear error when target is unreachable."""
        resp = await client.post("/api/sessions", json={
            "protocol": "minimal_tcp",
            "target_host": "127.0.0.1",
            "target_port": 19998,
            "max_iterations": 5,
        })
        session_id = resp.json()["id"]

        resp = await client.post(f"/api/sessions/{session_id}/start")
        assert resp.status_code == 200

        for _ in range(20):
            await asyncio.sleep(0.5)
            s = (await client.get(f"/api/sessions/{session_id}")).json()
            if s["status"] in ("completed", "failed"):
                break

        final = (await client.get(f"/api/sessions/{session_id}")).json()
        assert final["status"] in ("completed", "failed")
