"""Tests for the Core API routes."""
import pytest
from fastapi.testclient import TestClient

from core.api.server import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestSystemRoutes:
    def test_health_endpoint(self, client):
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_root_without_ui_build(self, client):
        resp = client.get("/", follow_redirects=False)
        # Either redirects to /ui/ or returns info JSON
        assert resp.status_code in (200, 307)


class TestPluginRoutes:
    def test_list_plugins(self, client):
        resp = client.get("/api/plugins")
        assert resp.status_code == 200
        plugins = resp.json()
        assert isinstance(plugins, list)
        assert len(plugins) > 0
        # Standard plugins should be discovered
        assert "dns" in plugins or "minimal_tcp" in plugins

    def test_get_plugin(self, client):
        resp = client.get("/api/plugins/minimal_tcp")
        assert resp.status_code == 200
        plugin = resp.json()
        assert plugin["name"] == "minimal_tcp"
        assert "blocks" in plugin["data_model"]

    def test_get_nonexistent_plugin(self, client):
        resp = client.get("/api/plugins/nonexistent_xyz")
        assert resp.status_code == 404

    def test_list_mutators(self, client):
        resp = client.get("/api/mutators")
        assert resp.status_code == 200
        data = resp.json()
        assert "mutators" in data
        assert "mutation_modes" in data
        assert len(data["mutators"]) >= 6

    def test_validate_plugin(self, client):
        resp = client.get("/api/plugins/minimal_tcp/validate")
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert "issues" in data


class TestSessionRoutes:
    def test_list_sessions_empty(self, client):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_session(self, client):
        resp = client.post("/api/sessions", json={
            "protocol": "minimal_tcp",
            "target_host": "localhost",
            "target_port": 9999,
        })
        assert resp.status_code == 200
        session = resp.json()
        assert session["protocol"] == "minimal_tcp"
        assert session["status"] == "idle"
        assert session["target_host"] == "localhost"
        assert session["target_port"] == 9999
        assert len(session["seed_corpus"]) > 0

        # Verify it appears in listing
        resp2 = client.get("/api/sessions")
        ids = [s["id"] for s in resp2.json()]
        assert session["id"] in ids

    def test_create_session_invalid_protocol(self, client):
        resp = client.post("/api/sessions", json={
            "protocol": "nonexistent_proto",
            "target_host": "localhost",
            "target_port": 9999,
        })
        assert resp.status_code == 500

    def test_get_session(self, client):
        # Create first
        resp = client.post("/api/sessions", json={
            "protocol": "minimal_tcp",
            "target_host": "localhost",
            "target_port": 9999,
        })
        session_id = resp.json()["id"]

        # Fetch
        resp2 = client.get(f"/api/sessions/{session_id}")
        assert resp2.status_code == 200
        assert resp2.json()["id"] == session_id

    def test_get_nonexistent_session(self, client):
        resp = client.get("/api/sessions/nonexistent-id")
        assert resp.status_code == 404

    def test_delete_session(self, client):
        resp = client.post("/api/sessions", json={
            "protocol": "minimal_tcp",
            "target_host": "localhost",
            "target_port": 9999,
        })
        session_id = resp.json()["id"]

        resp2 = client.delete(f"/api/sessions/{session_id}")
        assert resp2.status_code == 200

        resp3 = client.get(f"/api/sessions/{session_id}")
        assert resp3.status_code == 404


class TestOneOffTestRoute:
    def test_one_off_without_target(self, client):
        """One-off test should fail gracefully when target is unreachable."""
        import base64
        payload = base64.b64encode(b"STCP\x00\x00\x00\x05\x01HELLO").decode()
        resp = client.post("/api/tests/execute", json={
            "protocol": "minimal_tcp",
            "target_host": "127.0.0.1",
            "target_port": 19999,  # Nothing listening here
            "payload": payload,
        })
        # Should return result (possibly with error) not crash
        assert resp.status_code in (200, 400, 500)
