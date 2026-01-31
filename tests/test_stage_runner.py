"""
Tests for StageRunner - orchestrated session stage execution.

Tests cover:
- Bootstrap stage execution
- Response validation (expect)
- Context value extraction (exports)
- Transform support in exports
- Retry logic
- Error handling
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from core.engine.stage_runner import (
    StageRunner,
    BootstrapError,
    BootstrapValidationError,
)
from core.engine.protocol_context import ProtocolContext
from core.models import FuzzSession, FuzzSessionStatus, TestCaseResult


class MockPluginManager:
    """Mock plugin manager for testing."""

    def __init__(self):
        self.plugins = {}

    def load_plugin(self, name):
        return self.plugins.get(name)


class TestStageRunnerBootstrap:
    """Tests for bootstrap stage execution."""

    @pytest.fixture
    def context(self):
        return ProtocolContext()

    @pytest.fixture
    def plugin_manager(self):
        return MockPluginManager()

    @pytest.fixture
    def session(self):
        return FuzzSession(
            id="test-session-1",
            protocol="test_protocol",
            target_host="localhost",
            target_port=9999,
            status=FuzzSessionStatus.IDLE,
        )

    @pytest.fixture
    def simple_bootstrap_stage(self):
        """Simple bootstrap stage with one export."""
        return {
            "name": "handshake",
            "role": "bootstrap",
            "data_model": {
                "blocks": [
                    {"name": "magic", "type": "bytes", "size": 4, "default": b"HSHK"},
                    {"name": "version", "type": "uint8", "default": 1},
                ]
            },
            "response_model": {
                "blocks": [
                    {"name": "magic", "type": "bytes", "size": 4},
                    {"name": "status", "type": "uint8"},
                    {"name": "token", "type": "uint32", "endian": "big"},
                ]
            },
            "exports": {
                "token": "auth_token",
            },
        }

    @pytest.mark.asyncio
    async def test_bootstrap_exports_to_context(
        self, context, plugin_manager, session, simple_bootstrap_stage
    ):
        """Test that bootstrap stage exports values to context."""
        runner = StageRunner(plugin_manager, context)

        # Mock the transport
        mock_response = b"RESP\x00\x12\x34\x56\x78"  # status=0, token=0x12345678

        with patch.object(runner, "_create_transport") as mock_create:
            mock_transport = AsyncMock()
            mock_transport.send_and_receive.return_value = (
                TestCaseResult.PASS,
                mock_response,
            )
            mock_create.return_value = mock_transport

            await runner.run_bootstrap_stages(session, [simple_bootstrap_stage])

        # Check that token was exported to context
        assert context.get("auth_token") == 0x12345678
        assert context.bootstrap_complete is True

    @pytest.mark.asyncio
    async def test_bootstrap_with_expect_validation(
        self, context, plugin_manager, session
    ):
        """Test that expect validation works."""
        stage = {
            "name": "handshake",
            "role": "bootstrap",
            "data_model": {
                "blocks": [
                    {"name": "cmd", "type": "uint8", "default": 1},
                ]
            },
            "response_model": {
                "blocks": [
                    {"name": "status", "type": "uint8"},
                ]
            },
            "expect": {
                "status": 0x00,  # Expect success status
            },
        }

        runner = StageRunner(plugin_manager, context)

        # Test successful validation
        mock_response = b"\x00"  # status = 0x00 (success)

        with patch.object(runner, "_create_transport") as mock_create:
            mock_transport = AsyncMock()
            mock_transport.send_and_receive.return_value = (
                TestCaseResult.PASS,
                mock_response,
            )
            mock_create.return_value = mock_transport

            # Should not raise
            await runner.run_bootstrap_stages(session, [stage])

    @pytest.mark.asyncio
    async def test_bootstrap_expect_validation_fails(
        self, context, plugin_manager, session
    ):
        """Test that expect validation raises on mismatch."""
        stage = {
            "name": "handshake",
            "role": "bootstrap",
            "data_model": {
                "blocks": [
                    {"name": "cmd", "type": "uint8", "default": 1},
                ]
            },
            "response_model": {
                "blocks": [
                    {"name": "status", "type": "uint8"},
                ]
            },
            "expect": {
                "status": 0x00,  # Expect success
            },
        }

        runner = StageRunner(plugin_manager, context)

        # Return error status
        mock_response = b"\x01"  # status = 0x01 (error)

        with patch.object(runner, "_create_transport") as mock_create:
            mock_transport = AsyncMock()
            mock_transport.send_and_receive.return_value = (
                TestCaseResult.PASS,
                mock_response,
            )
            mock_create.return_value = mock_transport

            with pytest.raises(BootstrapValidationError) as exc_info:
                await runner.run_bootstrap_stages(session, [stage])

            assert exc_info.value.field == "status"
            assert exc_info.value.expected == 0x00
            assert exc_info.value.actual == 0x01

    @pytest.mark.asyncio
    async def test_bootstrap_retry_on_failure(
        self, context, plugin_manager, session
    ):
        """Test that bootstrap retries on transport failure."""
        stage = {
            "name": "handshake",
            "role": "bootstrap",
            "data_model": {
                "blocks": [
                    {"name": "cmd", "type": "uint8", "default": 1},
                ]
            },
            "response_model": {
                "blocks": [
                    {"name": "status", "type": "uint8"},
                ]
            },
            "retry": {
                "max_attempts": 3,
                "backoff_ms": 10,  # Short backoff for testing
            },
        }

        runner = StageRunner(plugin_manager, context)

        # First two attempts fail, third succeeds
        call_count = 0

        async def mock_send(*args):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return (TestCaseResult.HANG, None)
            return (TestCaseResult.PASS, b"\x00")

        with patch.object(runner, "_create_transport") as mock_create:
            mock_transport = AsyncMock()
            mock_transport.send_and_receive.side_effect = mock_send
            mock_create.return_value = mock_transport

            await runner.run_bootstrap_stages(session, [stage])

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_bootstrap_retry_exhausted(
        self, context, plugin_manager, session
    ):
        """Test that bootstrap fails after all retries exhausted."""
        stage = {
            "name": "handshake",
            "role": "bootstrap",
            "data_model": {
                "blocks": [
                    {"name": "cmd", "type": "uint8", "default": 1},
                ]
            },
            "retry": {
                "max_attempts": 2,
                "backoff_ms": 10,
            },
        }

        runner = StageRunner(plugin_manager, context)

        with patch.object(runner, "_create_transport") as mock_create:
            mock_transport = AsyncMock()
            mock_transport.send_and_receive.return_value = (TestCaseResult.HANG, None)
            mock_create.return_value = mock_transport

            with pytest.raises(BootstrapError) as exc_info:
                await runner.run_bootstrap_stages(session, [stage])

            assert "2 attempts" in str(exc_info.value)


class TestStageRunnerExports:
    """Tests for export functionality."""

    @pytest.fixture
    def context(self):
        return ProtocolContext()

    @pytest.fixture
    def plugin_manager(self):
        return MockPluginManager()

    @pytest.fixture
    def session(self):
        return FuzzSession(
            id="test-session-1",
            protocol="test_protocol",
            target_host="localhost",
            target_port=9999,
            status=FuzzSessionStatus.IDLE,
        )

    @pytest.mark.asyncio
    async def test_export_with_transform(self, context, plugin_manager, session):
        """Test exports with transform operations."""
        stage = {
            "name": "handshake",
            "role": "bootstrap",
            "data_model": {
                "blocks": [
                    {"name": "cmd", "type": "uint8", "default": 1},
                ]
            },
            "response_model": {
                "blocks": [
                    {"name": "raw_token", "type": "uint16", "endian": "big"},
                ]
            },
            "exports": {
                "raw_token": {
                    "as": "masked_token",
                    "transform": [
                        {"operation": "and_mask", "value": 0x00FF},
                    ],
                },
            },
        }

        runner = StageRunner(plugin_manager, context)

        # Response with raw_token = 0xABCD
        mock_response = b"\xAB\xCD"

        with patch.object(runner, "_create_transport") as mock_create:
            mock_transport = AsyncMock()
            mock_transport.send_and_receive.return_value = (
                TestCaseResult.PASS,
                mock_response,
            )
            mock_create.return_value = mock_transport

            await runner.run_bootstrap_stages(session, [stage])

        # Token should be masked: 0xABCD & 0x00FF = 0x00CD
        assert context.get("masked_token") == 0xCD

    @pytest.mark.asyncio
    async def test_export_multiple_values(self, context, plugin_manager, session):
        """Test exporting multiple values from response."""
        stage = {
            "name": "handshake",
            "role": "bootstrap",
            "data_model": {
                "blocks": [
                    {"name": "cmd", "type": "uint8", "default": 1},
                ]
            },
            "response_model": {
                "blocks": [
                    {"name": "token", "type": "uint32", "endian": "big"},
                    {"name": "nonce", "type": "uint32", "endian": "big"},
                    {"name": "interval", "type": "uint16", "endian": "big"},
                ]
            },
            "exports": {
                "token": "auth_token",
                "nonce": "server_nonce",
                "interval": "heartbeat_interval",
            },
        }

        runner = StageRunner(plugin_manager, context)

        # Response: token=0x11111111, nonce=0x22222222, interval=0x3333
        mock_response = b"\x11\x11\x11\x11\x22\x22\x22\x22\x33\x33"

        with patch.object(runner, "_create_transport") as mock_create:
            mock_transport = AsyncMock()
            mock_transport.send_and_receive.return_value = (
                TestCaseResult.PASS,
                mock_response,
            )
            mock_create.return_value = mock_transport

            await runner.run_bootstrap_stages(session, [stage])

        assert context.get("auth_token") == 0x11111111
        assert context.get("server_nonce") == 0x22222222
        assert context.get("heartbeat_interval") == 0x3333


class TestStageRunnerStatus:
    """Tests for stage status tracking."""

    @pytest.fixture
    def context(self):
        return ProtocolContext()

    @pytest.fixture
    def plugin_manager(self):
        return MockPluginManager()

    @pytest.fixture
    def session(self):
        return FuzzSession(
            id="test-session-1",
            protocol="test_protocol",
            target_host="localhost",
            target_port=9999,
            status=FuzzSessionStatus.IDLE,
        )

    @pytest.mark.asyncio
    async def test_stage_status_tracking(self, context, plugin_manager, session):
        """Test that stage statuses are properly tracked."""
        stage = {
            "name": "handshake",
            "role": "bootstrap",
            "data_model": {
                "blocks": [
                    {"name": "cmd", "type": "uint8", "default": 1},
                ]
            },
            "response_model": {
                "blocks": [
                    {"name": "status", "type": "uint8"},
                ]
            },
        }

        runner = StageRunner(plugin_manager, context)

        with patch.object(runner, "_create_transport") as mock_create:
            mock_transport = AsyncMock()
            mock_transport.send_and_receive.return_value = (
                TestCaseResult.PASS,
                b"\x00",
            )
            mock_create.return_value = mock_transport

            await runner.run_bootstrap_stages(session, [stage])

        status = runner.get_stage_status("handshake")
        assert status is not None
        assert status.name == "handshake"
        assert status.role == "bootstrap"
        assert status.status == "complete"
        assert status.started_at is not None
        assert status.completed_at is not None

    @pytest.mark.asyncio
    async def test_stage_status_on_failure(self, context, plugin_manager, session):
        """Test that failed stage status is properly tracked."""
        stage = {
            "name": "handshake",
            "role": "bootstrap",
            "data_model": {
                "blocks": [
                    {"name": "cmd", "type": "uint8", "default": 1},
                ]
            },
            "retry": {"max_attempts": 1},
        }

        runner = StageRunner(plugin_manager, context)

        with patch.object(runner, "_create_transport") as mock_create:
            mock_transport = AsyncMock()
            mock_transport.send_and_receive.return_value = (TestCaseResult.HANG, None)
            mock_create.return_value = mock_transport

            with pytest.raises(BootstrapError):
                await runner.run_bootstrap_stages(session, [stage])

        status = runner.get_stage_status("handshake")
        assert status is not None
        assert status.status == "failed"
        assert status.error_message is not None


class TestStageRunnerHelpers:
    """Tests for helper methods."""

    def test_get_fuzz_target_stage(self):
        """Test getting fuzz target stage from protocol stack."""
        context = ProtocolContext()
        runner = StageRunner(MockPluginManager(), context)

        stages = [
            {"name": "bootstrap", "role": "bootstrap"},
            {"name": "application", "role": "fuzz_target"},
            {"name": "cleanup", "role": "teardown"},
        ]

        fuzz_stage = runner.get_fuzz_target_stage(stages)
        assert fuzz_stage is not None
        assert fuzz_stage["name"] == "application"

    def test_get_fuzz_target_stage_none(self):
        """Test getting fuzz target stage when none exists."""
        context = ProtocolContext()
        runner = StageRunner(MockPluginManager(), context)

        stages = [
            {"name": "bootstrap", "role": "bootstrap"},
        ]

        fuzz_stage = runner.get_fuzz_target_stage(stages)
        assert fuzz_stage is None

    def test_reset_for_reconnect(self):
        """Test reset_for_reconnect clears context and statuses."""
        context = ProtocolContext()
        context.set("token", 12345)
        context.bootstrap_complete = True

        runner = StageRunner(MockPluginManager(), context)
        runner._stage_statuses["test"] = MagicMock(role="bootstrap", status="complete")

        runner.reset_for_reconnect(clear_context=True)

        assert context.get("token") is None
        assert context.bootstrap_complete is False
        assert runner._stage_statuses["test"].status == "pending"
