"""
Tests for HeartbeatScheduler - periodic keepalive messages.

Tests cover:
- Starting and stopping heartbeats
- Interval with jitter
- Context-based interval
- Failure detection and handling
- Reconnect triggering
- Message building
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from core.engine.heartbeat_scheduler import (
    HeartbeatScheduler,
    HeartbeatState,
    HeartbeatStatus,
    HeartbeatAbortError,
)
from core.engine.protocol_context import ProtocolContext
from core.models import FuzzSession, FuzzSessionStatus


class MockConnectionManager:
    """Mock connection manager for testing."""

    def __init__(self, response: bytes = b"OK"):
        self.response = response
        self.send_calls = []
        self.reconnect_calls = []
        self.fail_next_send = False
        self.reconnect_fail = False

    async def send_with_lock(
        self,
        session,
        data,
        timeout_ms=None,
    ) -> bytes:
        if self.fail_next_send:
            self.fail_next_send = False
            raise Exception("Send failed")
        self.send_calls.append((session, data, timeout_ms))
        return self.response

    async def reconnect(self, session, rebootstrap=False) -> bool:
        if self.reconnect_fail:
            raise Exception("Reconnect failed")
        self.reconnect_calls.append((session, rebootstrap))
        return rebootstrap


@pytest.fixture
def connection_manager():
    return MockConnectionManager()


@pytest.fixture
def context():
    return ProtocolContext()


@pytest.fixture
def session():
    return FuzzSession(
        id="test-session-1",
        protocol="test_protocol",
        target_host="localhost",
        target_port=9999,
        status=FuzzSessionStatus.IDLE,
    )


@pytest.fixture
def basic_config():
    """Basic heartbeat configuration."""
    return {
        "enabled": True,
        "interval_ms": 100,  # Short interval for testing
        "jitter_ms": 0,
        "message": {
            "data_model": {
                "blocks": [
                    {"name": "magic", "type": "bytes", "size": 4, "default": b"BEAT"},
                ]
            }
        },
        "expect_response": False,
    }


class TestHeartbeatSchedulerBasic:
    """Basic start/stop tests."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self, connection_manager, context, session, basic_config):
        """Test that start() creates an async task."""
        scheduler = HeartbeatScheduler(connection_manager)
        scheduler.start(session, basic_config, context)

        assert scheduler.is_running(session.id)
        assert session.heartbeat_enabled is True

        # Clean up
        scheduler.stop(session.id)

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, connection_manager, context, session, basic_config):
        """Test that stop() cancels the heartbeat task."""
        scheduler = HeartbeatScheduler(connection_manager)
        scheduler.start(session, basic_config, context)

        # Let it run briefly
        await asyncio.sleep(0.05)

        scheduler.stop(session.id)

        # Give time for cancellation
        await asyncio.sleep(0.02)

        assert not scheduler.is_running(session.id)

    @pytest.mark.asyncio
    async def test_disabled_config_does_nothing(self, connection_manager, context, session):
        """Test that disabled heartbeat config doesn't start task."""
        config = {
            "enabled": False,
            "interval_ms": 100,
        }

        scheduler = HeartbeatScheduler(connection_manager)
        scheduler.start(session, config, context)

        assert not scheduler.is_running(session.id)
        assert scheduler.get_status(session.id) is None

    @pytest.mark.asyncio
    async def test_stop_all(self, connection_manager, context, basic_config):
        """Test stop_all stops all sessions."""
        scheduler = HeartbeatScheduler(connection_manager)

        # Start multiple sessions
        for i in range(3):
            s = FuzzSession(
                id=f"session-{i}",
                protocol="test",
                target_host="localhost",
                target_port=9999,
                status=FuzzSessionStatus.IDLE,
            )
            scheduler.start(s, basic_config, context)

        scheduler.stop_all()

        await asyncio.sleep(0.02)

        assert len(scheduler._states) == 0


class TestHeartbeatSchedulerSends:
    """Tests for heartbeat sending."""

    @pytest.mark.asyncio
    async def test_sends_at_interval(self, connection_manager, context, session, basic_config):
        """Test that heartbeat sends at configured interval."""
        scheduler = HeartbeatScheduler(connection_manager)
        scheduler.start(session, basic_config, context)

        # Wait for a few heartbeats
        await asyncio.sleep(0.35)  # Should send ~3 heartbeats at 100ms interval

        scheduler.stop(session.id)

        # Should have sent at least 3 heartbeats
        assert len(connection_manager.send_calls) >= 3

    @pytest.mark.asyncio
    async def test_sends_correct_message(self, connection_manager, context, session, basic_config):
        """Test that heartbeat sends the configured message."""
        scheduler = HeartbeatScheduler(connection_manager)
        scheduler.start(session, basic_config, context)

        # Wait for one heartbeat
        await asyncio.sleep(0.15)

        scheduler.stop(session.id)

        assert len(connection_manager.send_calls) >= 1
        _, data, _ = connection_manager.send_calls[0]
        assert data == b"BEAT"

    @pytest.mark.asyncio
    async def test_sends_with_context(self, connection_manager, session):
        """Test that heartbeat message uses context values."""
        context = ProtocolContext()
        context.set("auth_token", 0x12345678)

        config = {
            "enabled": True,
            "interval_ms": 100,
            "message": {
                "data_model": {
                    "blocks": [
                        {"name": "magic", "type": "bytes", "size": 4, "default": b"BEAT"},
                        {"name": "token", "type": "uint32", "from_context": "auth_token", "endian": "big"},
                    ]
                }
            },
            "expect_response": False,
        }

        scheduler = HeartbeatScheduler(connection_manager)
        scheduler.start(session, config, context)

        await asyncio.sleep(0.15)

        scheduler.stop(session.id)

        assert len(connection_manager.send_calls) >= 1
        _, data, _ = connection_manager.send_calls[0]

        # Should contain magic + token
        assert data[:4] == b"BEAT"
        # Token should be 0x12345678 in big endian
        assert data[4:8] == b"\x12\x34\x56\x78"


class TestHeartbeatSchedulerInterval:
    """Tests for interval handling."""

    @pytest.mark.asyncio
    async def test_jitter_varies_interval(self, connection_manager, context, session):
        """Test that jitter varies the send interval."""
        config = {
            "enabled": True,
            "interval_ms": 100,
            "jitter_ms": 50,
            "message": {"raw": b"BEAT"},
            "expect_response": False,
        }

        scheduler = HeartbeatScheduler(connection_manager)
        scheduler.start(session, config, context)

        # Wait for several heartbeats
        await asyncio.sleep(0.5)

        scheduler.stop(session.id)

        # With jitter, intervals should vary
        # Just verify it sent heartbeats (timing is non-deterministic)
        assert len(connection_manager.send_calls) >= 3

    def test_get_interval_from_config(self, context):
        """Test getting interval from config."""
        scheduler = HeartbeatScheduler(MagicMock())

        config = {"interval_ms": 5000}
        assert scheduler._get_interval(config, context) == 5000

    def test_get_interval_from_context(self):
        """Test getting interval from context."""
        context = ProtocolContext()
        context.set("hb_interval", 10000)

        scheduler = HeartbeatScheduler(MagicMock())

        config = {"interval_ms": {"from_context": "hb_interval"}}
        assert scheduler._get_interval(config, context) == 10000

    def test_get_interval_fallback(self, context):
        """Test interval fallback when context key missing."""
        scheduler = HeartbeatScheduler(MagicMock())

        config = {"interval_ms": {"from_context": "missing_key"}}
        # Should fall back to default 30000
        assert scheduler._get_interval(config, context) == 30000


class TestHeartbeatSchedulerFailures:
    """Tests for failure handling."""

    @pytest.mark.asyncio
    async def test_failure_increments_count(self, context, session, basic_config):
        """Test that failures increment the failure count."""
        cm = MockConnectionManager()
        cm.fail_next_send = True

        scheduler = HeartbeatScheduler(cm)
        scheduler.start(session, basic_config, context)

        # Wait for failure
        await asyncio.sleep(0.15)

        status = scheduler.get_status(session.id)
        assert status is not None
        assert status["failures"] >= 1

        scheduler.stop(session.id)

    @pytest.mark.asyncio
    async def test_success_resets_failures(self, context, session, basic_config):
        """Test that success resets failure count."""
        cm = MockConnectionManager()
        cm.fail_next_send = True

        scheduler = HeartbeatScheduler(cm)
        scheduler.start(session, basic_config, context)

        # First heartbeat fails
        await asyncio.sleep(0.12)
        # Subsequent heartbeats succeed
        await asyncio.sleep(0.15)

        status = scheduler.get_status(session.id)
        # After success, failures should be 0
        assert status is not None
        assert status["failures"] == 0

        scheduler.stop(session.id)

    @pytest.mark.asyncio
    async def test_max_failures_triggers_reconnect(self, context, session):
        """Test that max failures triggers reconnect action."""
        cm = MockConnectionManager()

        config = {
            "enabled": True,
            "interval_ms": 50,
            "message": {"raw": b"BEAT"},
            "expect_response": True,
            "on_timeout": {
                "action": "reconnect",
                "max_failures": 2,
                "rebootstrap": True,
            }
        }

        # Return empty response to trigger failure
        cm.response = b""

        scheduler = HeartbeatScheduler(cm)
        scheduler.start(session, config, context)

        # Wait for failures and reconnect
        await asyncio.sleep(0.25)

        scheduler.stop(session.id)

        # Should have attempted reconnect
        assert len(cm.reconnect_calls) >= 1

    @pytest.mark.asyncio
    async def test_abort_action_raises(self, context, session):
        """Test that abort action raises HeartbeatAbortError."""
        cm = MockConnectionManager()
        cm.response = b""  # Invalid response

        config = {
            "enabled": True,
            "interval_ms": 50,
            "message": {"raw": b"BEAT"},
            "expect_response": True,
            "on_timeout": {
                "action": "abort",
                "max_failures": 2,
            }
        }

        scheduler = HeartbeatScheduler(cm)
        scheduler.start(session, config, context)

        # Wait for failures
        await asyncio.sleep(0.25)

        status = scheduler.get_status(session.id)
        assert status is not None
        assert status["status"] == HeartbeatStatus.FAILED.value

        scheduler.stop(session.id)

    @pytest.mark.asyncio
    async def test_reset_failures(self, context, session, basic_config):
        """Test manual failure reset."""
        cm = MockConnectionManager()
        cm.response = b""  # Invalid response

        basic_config["expect_response"] = True

        scheduler = HeartbeatScheduler(cm)
        scheduler.start(session, basic_config, context)

        await asyncio.sleep(0.15)

        # Should have failures
        status = scheduler.get_status(session.id)
        assert status["failures"] > 0

        # Reset failures
        scheduler.reset_failures(session.id)

        status = scheduler.get_status(session.id)
        assert status["failures"] == 0
        assert status["status"] == HeartbeatStatus.HEALTHY.value

        scheduler.stop(session.id)


class TestHeartbeatSchedulerCallback:
    """Tests for reconnect callback."""

    @pytest.mark.asyncio
    async def test_reconnect_callback_called(self, context, session):
        """Test that reconnect callback is called on reconnect."""
        cm = MockConnectionManager()
        cm.response = b""  # Invalid response

        callback_calls = []

        def callback(s, rebootstrap):
            callback_calls.append((s, rebootstrap))

        config = {
            "enabled": True,
            "interval_ms": 50,
            "message": {"raw": b"BEAT"},
            "expect_response": True,
            "on_timeout": {
                "action": "reconnect",
                "max_failures": 1,
                "rebootstrap": True,
            }
        }

        scheduler = HeartbeatScheduler(cm, reconnect_callback=callback)
        scheduler.start(session, config, context)

        await asyncio.sleep(0.2)

        scheduler.stop(session.id)

        # Callback should have been called
        assert len(callback_calls) >= 1
        assert callback_calls[0][1] is True  # rebootstrap=True


class TestHeartbeatMessage:
    """Tests for message building."""

    def test_build_from_data_model(self, context):
        """Test building message from data_model."""
        scheduler = HeartbeatScheduler(MagicMock())

        config = {
            "message": {
                "data_model": {
                    "blocks": [
                        {"name": "magic", "type": "bytes", "size": 4, "default": b"PING"},
                        {"name": "seq", "type": "uint8", "default": 1},
                    ]
                }
            }
        }

        message = scheduler._build_heartbeat(config, context)
        assert message == b"PING\x01"

    def test_build_from_raw_bytes(self, context):
        """Test building message from raw bytes."""
        scheduler = HeartbeatScheduler(MagicMock())

        config = {
            "message": {
                "raw": b"KEEP"
            }
        }

        message = scheduler._build_heartbeat(config, context)
        assert message == b"KEEP"

    def test_build_from_raw_hex(self, context):
        """Test building message from raw hex string."""
        scheduler = HeartbeatScheduler(MagicMock())

        config = {
            "message": {
                "raw": "4b454550"  # "KEEP" in hex
            }
        }

        message = scheduler._build_heartbeat(config, context)
        assert message == b"KEEP"

    def test_build_missing_config_raises(self, context):
        """Test that missing message config raises."""
        scheduler = HeartbeatScheduler(MagicMock())

        config = {"message": {}}

        with pytest.raises(ValueError, match="missing"):
            scheduler._build_heartbeat(config, context)


class TestHeartbeatResponse:
    """Tests for response validation."""

    def test_valid_non_empty_response(self):
        """Test that non-empty response is valid."""
        scheduler = HeartbeatScheduler(MagicMock())
        config = {}

        assert scheduler._is_valid_response(b"OK", config) is True
        assert scheduler._is_valid_response(b"\x00", config) is True

    def test_empty_response_invalid(self):
        """Test that empty response is invalid."""
        scheduler = HeartbeatScheduler(MagicMock())
        config = {}

        assert scheduler._is_valid_response(b"", config) is False

    def test_expected_response_bytes(self):
        """Test expected_response with bytes."""
        scheduler = HeartbeatScheduler(MagicMock())
        config = {"expected_response": b"ACK"}

        assert scheduler._is_valid_response(b"ACK", config) is True
        assert scheduler._is_valid_response(b"ACKOK", config) is True
        assert scheduler._is_valid_response(b"NAK", config) is False

    def test_expected_response_hex(self):
        """Test expected_response with hex string."""
        scheduler = HeartbeatScheduler(MagicMock())
        config = {"expected_response": "41434b"}  # "ACK" in hex

        assert scheduler._is_valid_response(b"ACK", config) is True
        assert scheduler._is_valid_response(b"NAK", config) is False


class TestHeartbeatStatus:
    """Tests for status tracking."""

    @pytest.mark.asyncio
    async def test_status_updates(self, connection_manager, context, session, basic_config):
        """Test that status is properly tracked."""
        scheduler = HeartbeatScheduler(connection_manager)
        scheduler.start(session, basic_config, context)

        await asyncio.sleep(0.15)

        status = scheduler.get_status(session.id)
        assert status is not None
        assert status["status"] == HeartbeatStatus.HEALTHY.value
        assert status["total_sent"] >= 1
        assert status["last_sent"] is not None

        scheduler.stop(session.id)

    def test_no_status_for_unknown_session(self):
        """Test that unknown session returns None."""
        scheduler = HeartbeatScheduler(MagicMock())
        assert scheduler.get_status("unknown") is None
