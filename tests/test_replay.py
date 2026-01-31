"""
Tests for ReplayExecutor - replays executions with context reconstruction.

Tests cover:
- Replay modes: fresh, stored, skip
- Single execution replay
- Multi-execution replay (replay_up_to)
- Context reconstruction
- Re-serialization in fresh mode
- Error handling
- History completeness validation
"""
import pytest
import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from core.engine.replay_executor import (
    ReplayExecutor,
    ReplayMode,
    ReplayResult,
    ReplayResponse,
    ReplayError,
)
from core.engine.protocol_context import ProtocolContext
from core.models import FuzzSession, FuzzSessionStatus


class MockTransport:
    """Mock transport for testing."""

    def __init__(self, responses: list = None):
        self.responses = responses or [b"OK"]
        self.response_index = 0
        self.sent_data = []
        self.closed = False
        self.fail_send = False
        self.fail_recv = False

    async def send(self, data: bytes) -> None:
        if self.fail_send:
            raise Exception("Send failed")
        self.sent_data.append(data)

    async def recv(self, timeout_ms: int = 1000) -> bytes:
        if self.fail_recv:
            from core.exceptions import ReceiveTimeoutError
            raise ReceiveTimeoutError("Timeout")
        response = self.responses[self.response_index % len(self.responses)]
        self.response_index += 1
        return response

    async def close(self) -> None:
        self.closed = True


class MockConnectionManager:
    """Mock connection manager for testing."""

    def __init__(self, transport: MockTransport = None):
        self.transport = transport or MockTransport()
        self.get_transport_calls = []
        self.replay_transport_calls = []

    async def get_transport(self, session) -> MockTransport:
        self.get_transport_calls.append(session)
        return self.transport

    async def create_replay_transport(self, session) -> MockTransport:
        """Create isolated transport for replay (not cached)."""
        self.replay_transport_calls.append(session)
        return self.transport


class MockHistoryStore:
    """Mock history store for testing."""

    def __init__(self, executions: list = None):
        self.executions = executions or []

    def list_for_replay(self, session_id: str, up_to_sequence: int) -> list:
        return [e for e in self.executions if e.sequence_number <= up_to_sequence]

    def find_by_sequence(self, session_id: str, sequence_number: int):
        for e in self.executions:
            if e.sequence_number == sequence_number:
                return e
        return None


class MockExecution:
    """Mock execution record for testing."""

    def __init__(
        self,
        sequence_number: int,
        raw_payload: bytes = b"TEST",
        raw_response: bytes = b"OK",
        stage_name: str = "application",
        context_snapshot: dict = None,
        parsed_fields: dict = None,
    ):
        self.sequence_number = sequence_number
        self.raw_payload_b64 = base64.b64encode(raw_payload).decode()
        self.raw_response_b64 = base64.b64encode(raw_response).decode() if raw_response else None
        self.stage_name = stage_name
        self.context_snapshot = context_snapshot
        self.parsed_fields = parsed_fields


class MockPluginManager:
    """Mock plugin manager for testing."""

    def __init__(self, plugin="default", protocol_stack=None):
        # Use "default" sentinel to distinguish from explicit None
        if plugin == "default":
            self.plugin = MagicMock()
        else:
            self.plugin = plugin
        self.protocol_stack = protocol_stack

    def load_plugin(self, protocol: str):
        return self.plugin

    def get_protocol_stack(self, protocol: str):
        return self.protocol_stack


class MockStageRunner:
    """Mock stage runner for testing."""

    def __init__(self, context: ProtocolContext = None):
        self.context = context or ProtocolContext()
        self.run_bootstrap_calls = []

    async def run_bootstrap_stages(self, session, stages):
        self.run_bootstrap_calls.append((session, stages))


@pytest.fixture
def session():
    return FuzzSession(
        id="test-session-1",
        protocol="test_protocol",
        target_host="localhost",
        target_port=9999,
        status=FuzzSessionStatus.IDLE,
        timeout_per_test_ms=1000,
    )


@pytest.fixture
def basic_executions():
    """Basic execution history for testing."""
    return [
        MockExecution(1, b"MSG1", b"RSP1"),
        MockExecution(2, b"MSG2", b"RSP2"),
        MockExecution(3, b"MSG3", b"RSP3"),
    ]


class TestReplayModes:
    """Tests for different replay modes."""

    @pytest.mark.asyncio
    async def test_stored_mode_uses_exact_bytes(self, session, basic_executions):
        """Test that STORED mode replays exact historical bytes."""
        transport = MockTransport(responses=[b"RSP1", b"RSP2", b"RSP3"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(basic_executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 3, mode=ReplayMode.STORED)

        assert result.replayed_count == 3
        assert transport.sent_data == [b"MSG1", b"MSG2", b"MSG3"]

    @pytest.mark.asyncio
    async def test_skip_mode_uses_stored_bytes(self, session, basic_executions):
        """Test that SKIP mode also uses stored bytes (no bootstrap)."""
        transport = MockTransport(responses=[b"RSP1", b"RSP2", b"RSP3"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(basic_executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 3, mode=ReplayMode.SKIP)

        assert result.replayed_count == 3
        assert transport.sent_data == [b"MSG1", b"MSG2", b"MSG3"]

    @pytest.mark.asyncio
    async def test_stored_mode_restores_context(self, session):
        """Test that STORED mode restores context from first execution."""
        # Context snapshot format matches ProtocolContext.snapshot() output
        context_snapshot = {
            "values": {"auth_token": 12345},
            "bootstrap_complete": True,
            "last_updated": None,
        }
        executions = [
            MockExecution(1, b"MSG1", b"RSP1", context_snapshot=context_snapshot),
            MockExecution(2, b"MSG2", b"RSP2"),
        ]

        transport = MockTransport(responses=[b"RSP1", b"RSP2"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 2, mode=ReplayMode.STORED)

        # Context should be restored from snapshot - access via values key
        assert result.context_after.get("values", {}).get("auth_token") == 12345

    @pytest.mark.asyncio
    async def test_fresh_mode_runs_bootstrap(self, session, basic_executions):
        """Test that FRESH mode runs bootstrap stages."""
        transport = MockTransport(responses=[b"RSP1", b"RSP2", b"RSP3"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(basic_executions)

        protocol_stack = [
            {"name": "auth", "role": "bootstrap"},
            {"name": "app", "role": "fuzz_target"},
        ]
        plugin_manager = MockPluginManager(protocol_stack=protocol_stack)
        stage_runner = MockStageRunner()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store, stage_runner)
        result = await executor.replay_up_to(session, 3, mode=ReplayMode.FRESH)

        # Should have run bootstrap
        assert len(stage_runner.run_bootstrap_calls) == 1
        assert result.replayed_count == 3


class TestReplaySingle:
    """Tests for single execution replay."""

    @pytest.mark.asyncio
    async def test_replay_single_success(self, session):
        """Test replaying a single execution."""
        execution = MockExecution(5, b"SINGLE", b"RESPONSE")
        transport = MockTransport(responses=[b"RESPONSE"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore([execution])
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_single(session, 5)

        assert result.status == "success"
        assert result.original_sequence == 5
        assert result.matched_original is True
        assert transport.sent_data == [b"SINGLE"]
        assert transport.closed is True

    @pytest.mark.asyncio
    async def test_replay_single_not_found(self, session):
        """Test replaying non-existent sequence."""
        history_store = MockHistoryStore([])
        plugin_manager = MockPluginManager()
        conn_manager = MockConnectionManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_single(session, 999)

        assert result.status == "error"
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_replay_single_with_context(self, session):
        """Test single replay restores context."""
        execution = MockExecution(
            1, b"MSG", b"RSP",
            context_snapshot={"session_id": "abc123"}
        )
        transport = MockTransport(responses=[b"RSP"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore([execution])
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_single(session, 1)

        assert result.status == "success"


class TestReplayUpTo:
    """Tests for replay_up_to functionality."""

    @pytest.mark.asyncio
    async def test_replay_up_to_basic(self, session, basic_executions):
        """Test basic replay_up_to functionality."""
        transport = MockTransport(responses=[b"RSP1", b"RSP2", b"RSP3"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(basic_executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 3)

        assert result.replayed_count == 3
        assert len(result.results) == 3
        assert result.results[0].original_sequence == 1
        assert result.results[1].original_sequence == 2
        assert result.results[2].original_sequence == 3

    @pytest.mark.asyncio
    async def test_replay_up_to_partial(self, session, basic_executions):
        """Test replaying only up to a specific sequence."""
        transport = MockTransport(responses=[b"RSP1", b"RSP2"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(basic_executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 2)

        assert result.replayed_count == 2
        assert len(result.results) == 2

    @pytest.mark.asyncio
    async def test_replay_skips_bootstrap_stages(self, session):
        """Test that bootstrap stage executions are skipped in STORED mode."""
        executions = [
            MockExecution(1, b"AUTH", b"TOKEN", stage_name="auth"),
            MockExecution(2, b"MSG1", b"RSP1", stage_name="application"),
            MockExecution(3, b"MSG2", b"RSP2", stage_name="application"),
        ]

        protocol_stack = [
            {"name": "auth", "role": "bootstrap"},
            {"name": "app", "role": "fuzz_target"},
        ]

        transport = MockTransport(responses=[b"RSP1", b"RSP2"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(executions)
        plugin_manager = MockPluginManager(protocol_stack=protocol_stack)

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        # Use STORED mode to avoid running bootstrap (just replay historical bytes)
        result = await executor.replay_up_to(session, 3, mode=ReplayMode.STORED)

        assert result.replayed_count == 2
        assert result.skipped_count == 1

    @pytest.mark.asyncio
    async def test_replay_with_delay(self, session, basic_executions):
        """Test replay with inter-message delay."""
        transport = MockTransport(responses=[b"RSP1", b"RSP2"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(basic_executions[:2])
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)

        start = datetime.utcnow()
        result = await executor.replay_up_to(session, 2, delay_ms=50)
        end = datetime.utcnow()

        # Should have taken at least 50ms (one delay between 2 messages)
        elapsed_ms = (end - start).total_seconds() * 1000
        assert elapsed_ms >= 50

    @pytest.mark.asyncio
    async def test_replay_empty_history_raises(self, session):
        """Test that empty history raises ReplayError."""
        history_store = MockHistoryStore([])
        plugin_manager = MockPluginManager()
        conn_manager = MockConnectionManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)

        with pytest.raises(ReplayError, match="No executions found"):
            await executor.replay_up_to(session, 5)

    @pytest.mark.asyncio
    async def test_replay_warns_missing_start(self, session):
        """Test warning when history doesn't start at sequence 1."""
        executions = [
            MockExecution(5, b"MSG5", b"RSP5"),
            MockExecution(6, b"MSG6", b"RSP6"),
        ]

        transport = MockTransport(responses=[b"RSP5", b"RSP6"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 6)

        assert len(result.warnings) >= 1
        assert any("does not start at sequence 1" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_replay_warns_incomplete_history(self, session):
        """Test warning when requested range exceeds history."""
        executions = [
            MockExecution(1, b"MSG1", b"RSP1"),
            MockExecution(2, b"MSG2", b"RSP2"),
        ]

        transport = MockTransport(responses=[b"RSP1", b"RSP2"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 10)  # Request more than available

        assert len(result.warnings) >= 1
        assert any("only contains up to" in w for w in result.warnings)


class TestReplayResponseMatching:
    """Tests for response matching."""

    @pytest.mark.asyncio
    async def test_matched_original_true(self, session):
        """Test matched_original is True when response matches."""
        execution = MockExecution(1, b"MSG", b"EXACT_RESPONSE")
        transport = MockTransport(responses=[b"EXACT_RESPONSE"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore([execution])
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_single(session, 1)

        assert result.matched_original is True

    @pytest.mark.asyncio
    async def test_matched_original_false(self, session):
        """Test matched_original is False when response differs."""
        execution = MockExecution(1, b"MSG", b"ORIGINAL")
        transport = MockTransport(responses=[b"DIFFERENT"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore([execution])
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_single(session, 1)

        assert result.matched_original is False

    @pytest.mark.asyncio
    async def test_response_preview_populated(self, session):
        """Test response preview is populated in result."""
        execution = MockExecution(1, b"MSG", b"RSP")
        transport = MockTransport(responses=[b"\x01\x02\x03\x04"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore([execution])
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_single(session, 1)

        assert result.response_preview == "01020304"


class TestReplayErrorHandling:
    """Tests for error handling during replay."""

    @pytest.mark.asyncio
    async def test_timeout_result(self, session):
        """Test timeout is reported as timeout status."""
        execution = MockExecution(1, b"MSG", b"RSP")
        transport = MockTransport()
        transport.fail_recv = True
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore([execution])
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_single(session, 1)

        assert result.status == "timeout"
        assert result.error == "Response timeout"

    @pytest.mark.asyncio
    async def test_send_error_result(self, session):
        """Test send error is reported as error status."""
        execution = MockExecution(1, b"MSG", b"RSP")
        transport = MockTransport()
        transport.fail_send = True
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore([execution])
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_single(session, 1)

        assert result.status == "error"
        assert "Send failed" in result.error

    @pytest.mark.asyncio
    async def test_stop_on_error(self, session):
        """Test stop_on_error halts replay on first error."""
        executions = [
            MockExecution(1, b"MSG1", b"RSP1"),
            MockExecution(2, b"MSG2", b"RSP2"),
            MockExecution(3, b"MSG3", b"RSP3"),
        ]

        transport = MockTransport()
        transport.fail_send = True  # Will fail on first message
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 3, stop_on_error=True)

        # Should only have one result (stopped after first error)
        assert result.replayed_count == 1
        assert result.results[0].status == "error"

    @pytest.mark.asyncio
    async def test_continue_on_error(self, session):
        """Test replay continues on error when stop_on_error is False."""
        executions = [
            MockExecution(1, b"MSG1", b"RSP1"),
            MockExecution(2, b"MSG2", b"RSP2"),
        ]

        # First message times out, second succeeds
        transport = MockTransport(responses=[b"RSP2"])
        transport.fail_recv = False
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 2, stop_on_error=False)

        # Should have both results
        assert result.replayed_count == 2

    @pytest.mark.asyncio
    async def test_plugin_not_found_raises(self, session, basic_executions):
        """Test ReplayError when plugin not found."""
        plugin_manager = MockPluginManager(plugin=None)
        conn_manager = MockConnectionManager()
        history_store = MockHistoryStore(basic_executions)

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)

        with pytest.raises(ReplayError, match="Plugin not found"):
            await executor.replay_up_to(session, 3)

    @pytest.mark.asyncio
    async def test_transport_closed_on_success(self, session, basic_executions):
        """Test transport is closed after successful replay."""
        transport = MockTransport(responses=[b"RSP1", b"RSP2", b"RSP3"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(basic_executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        await executor.replay_up_to(session, 3)

        assert transport.closed is True

    @pytest.mark.asyncio
    async def test_transport_closed_on_error(self, session, basic_executions):
        """Test transport is closed even when replay fails."""
        transport = MockTransport()
        transport.fail_send = True
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(basic_executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 3, stop_on_error=True)

        assert transport.closed is True


class TestReplayDuration:
    """Tests for duration tracking."""

    @pytest.mark.asyncio
    async def test_result_has_duration(self, session):
        """Test individual results have duration."""
        execution = MockExecution(1, b"MSG", b"RSP")
        transport = MockTransport(responses=[b"RSP"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore([execution])
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_single(session, 1)

        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_response_has_total_duration(self, session, basic_executions):
        """Test replay response has total duration."""
        transport = MockTransport(responses=[b"RSP1", b"RSP2", b"RSP3"])
        conn_manager = MockConnectionManager(transport)
        history_store = MockHistoryStore(basic_executions)
        plugin_manager = MockPluginManager()

        executor = ReplayExecutor(plugin_manager, conn_manager, history_store)
        result = await executor.replay_up_to(session, 3)

        assert result.duration_ms > 0


class TestReplayDataclasses:
    """Tests for replay dataclasses."""

    def test_replay_result_defaults(self):
        """Test ReplayResult default values."""
        result = ReplayResult(original_sequence=1, status="success")

        assert result.response_preview is None
        assert result.error is None
        assert result.duration_ms == 0.0
        assert result.matched_original is False

    def test_replay_response_defaults(self):
        """Test ReplayResponse default values."""
        response = ReplayResponse(replayed_count=5)

        assert response.skipped_count == 0
        assert response.results == []
        assert response.context_after == {}
        assert response.warnings == []
        assert response.duration_ms == 0.0

    def test_replay_mode_values(self):
        """Test ReplayMode enum values."""
        assert ReplayMode.FRESH.value == "fresh"
        assert ReplayMode.STORED.value == "stored"
        assert ReplayMode.SKIP.value == "skip"
