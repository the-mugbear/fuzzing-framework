"""
Tests for ConnectionManager and ManagedTransport.

Tests cover:
- ManagedTransport connection lifecycle
- Send/receive coordination
- Statistics tracking
- ConnectionManager session management
- Connection modes (per_test, per_stage, session)
- Reconnect logic
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from core.engine.connection_manager import (
    ConnectionManager,
    ManagedTransport,
    PersistentTCPTransport,
    PendingRequest,
    ConnectionAbortError,
)
from core.models import FuzzSession, FuzzSessionStatus, TransportProtocol
from core.exceptions import TransportError, ReceiveTimeoutError


class TestPendingRequest:
    """Tests for PendingRequest class."""

    @pytest.mark.asyncio
    async def test_resolve_sets_result(self):
        """Test that resolve() sets the future result."""
        request = PendingRequest()
        test_data = b"test response"

        # Resolve in background
        async def resolve_later():
            await asyncio.sleep(0.01)
            request.resolve(test_data)

        asyncio.create_task(resolve_later())
        result = await request.wait()

        assert result == test_data

    @pytest.mark.asyncio
    async def test_wait_timeout(self):
        """Test that wait() times out."""
        request = PendingRequest(timeout_ms=50)

        with pytest.raises(ReceiveTimeoutError):
            await request.wait()

    @pytest.mark.asyncio
    async def test_fail_sets_exception(self):
        """Test that fail() sets an exception on the future."""
        request = PendingRequest()
        error = TransportError("Test error")

        async def fail_later():
            await asyncio.sleep(0.01)
            request.fail(error)

        asyncio.create_task(fail_later())

        with pytest.raises(TransportError, match="Test error"):
            await request.wait()


class TestManagedTransport:
    """Tests for ManagedTransport class."""

    @pytest.fixture
    def transport(self):
        return ManagedTransport(
            host="localhost",
            port=9999,
            timeout_ms=5000,
        )

    @pytest.mark.asyncio
    async def test_connect_establishes_connection(self, transport):
        """Test that connect() establishes a connection."""
        with patch.object(PersistentTCPTransport, "connect", new_callable=AsyncMock):
            await transport.connect()

        assert transport.connected is True
        assert transport.healthy is True
        assert transport.created_at is not None

    @pytest.mark.asyncio
    async def test_send_tracks_statistics(self, transport):
        """Test that send() tracks bytes and timestamps."""
        with patch.object(PersistentTCPTransport, "connect", new_callable=AsyncMock):
            await transport.connect()

        with patch.object(transport._transport, "send", new_callable=AsyncMock):
            await transport.send(b"test data")

        assert transport.bytes_sent == 9
        assert transport.send_count == 1
        assert transport.last_send is not None

    @pytest.mark.asyncio
    async def test_send_and_receive_coordination(self, transport):
        """Test that send_and_receive uses mutex."""
        with patch.object(PersistentTCPTransport, "connect", new_callable=AsyncMock):
            await transport.connect()

        mock_send = AsyncMock()
        mock_recv = AsyncMock(return_value=b"response")

        transport._transport.send = mock_send
        transport._transport.recv = mock_recv

        response = await transport.send_and_receive(b"request")

        assert response == b"response"
        assert transport.bytes_sent == 7
        assert transport.bytes_received == 8
        mock_send.assert_called_once_with(b"request")
        mock_recv.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_cleans_up(self, transport):
        """Test that close() properly cleans up."""
        with patch.object(PersistentTCPTransport, "connect", new_callable=AsyncMock):
            await transport.connect()

        with patch.object(transport._transport, "cleanup", new_callable=AsyncMock):
            await transport.close()

        assert transport.connected is False
        assert transport.healthy is False

    @pytest.mark.asyncio
    async def test_send_fails_when_not_connected(self, transport):
        """Test that send() fails when not connected."""
        with pytest.raises(TransportError, match="Not connected"):
            await transport.send(b"test")

    @pytest.mark.asyncio
    async def test_get_stats(self, transport):
        """Test get_stats() returns correct data."""
        with patch.object(PersistentTCPTransport, "connect", new_callable=AsyncMock):
            await transport.connect()

        stats = transport.get_stats()

        assert stats["connected"] is True
        assert stats["healthy"] is True
        assert stats["bytes_sent"] == 0
        assert stats["bytes_received"] == 0
        assert stats["created_at"] is not None


class TestConnectionManager:
    """Tests for ConnectionManager class."""

    @pytest.fixture
    def manager(self):
        return ConnectionManager()

    @pytest.fixture
    def session(self):
        return FuzzSession(
            id="test-session-1",
            protocol="test_protocol",
            target_host="localhost",
            target_port=9999,
            status=FuzzSessionStatus.IDLE,
            connection_mode="session",
        )

    @pytest.mark.asyncio
    async def test_get_transport_creates_new(self, manager, session):
        """Test that get_transport creates new transport."""
        with patch.object(ManagedTransport, "connect", new_callable=AsyncMock):
            transport = await manager.get_transport(session)

        assert transport is not None
        assert transport.host == "localhost"
        assert transport.port == 9999

    @pytest.mark.asyncio
    async def test_get_transport_reuses_healthy(self, manager, session):
        """Test that get_transport reuses healthy connection in session mode."""
        with patch.object(ManagedTransport, "connect", new_callable=AsyncMock):
            transport1 = await manager.get_transport(session)
            transport1.connected = True
            transport1.healthy = True

            transport2 = await manager.get_transport(session)

        assert transport1 is transport2

    @pytest.mark.asyncio
    async def test_get_transport_replaces_unhealthy(self, manager, session):
        """Test that get_transport replaces unhealthy connection."""
        with patch.object(ManagedTransport, "connect", new_callable=AsyncMock):
            with patch.object(ManagedTransport, "close", new_callable=AsyncMock):
                transport1 = await manager.get_transport(session)
                transport1.connected = True
                transport1.healthy = False

                transport2 = await manager.get_transport(session)

        assert transport1 is not transport2

    @pytest.mark.asyncio
    async def test_per_test_mode_always_new(self, manager, session):
        """Test that per_test mode always creates new connection."""
        session.connection_mode = "per_test"

        with patch.object(ManagedTransport, "connect", new_callable=AsyncMock):
            transport1 = await manager.get_transport(session)
            transport2 = await manager.get_transport(session)

        # per_test creates unique ID each time, so different transports
        assert transport1 is not transport2

    @pytest.mark.asyncio
    async def test_send_with_lock(self, manager, session):
        """Test send_with_lock sends and receives."""
        with patch.object(ManagedTransport, "connect", new_callable=AsyncMock):
            with patch.object(
                ManagedTransport,
                "send_and_receive",
                new_callable=AsyncMock,
                return_value=b"response",
            ):
                response = await manager.send_with_lock(session, b"request")

        assert response == b"response"

    @pytest.mark.asyncio
    async def test_reconnect_increments_count(self, manager, session):
        """Test that reconnect increments reconnect count."""
        manager.set_connection_config(session.id, {
            "on_drop": {"max_reconnects": 5, "backoff_ms": 0}
        })

        with patch.object(ManagedTransport, "connect", new_callable=AsyncMock):
            with patch.object(ManagedTransport, "close", new_callable=AsyncMock):
                # Create initial transport
                await manager.get_transport(session)

                # Reconnect
                rebootstrap = await manager.reconnect(session, rebootstrap=True)

        assert session.reconnect_count == 1
        assert rebootstrap is True

    @pytest.mark.asyncio
    async def test_reconnect_fails_after_max(self, manager, session):
        """Test that reconnect fails after max attempts."""
        session.reconnect_count = 5
        manager.set_connection_config(session.id, {
            "on_drop": {"max_reconnects": 5}
        })

        with pytest.raises(ConnectionAbortError, match="Max reconnects"):
            await manager.reconnect(session)

    @pytest.mark.asyncio
    async def test_close_session(self, manager, session):
        """Test close_session closes all transports."""
        with patch.object(ManagedTransport, "connect", new_callable=AsyncMock):
            await manager.get_transport(session)

        with patch.object(ManagedTransport, "close", new_callable=AsyncMock) as mock_close:
            await manager.close_session(session.id)

        mock_close.assert_called()

    @pytest.mark.asyncio
    async def test_close_all(self, manager, session):
        """Test close_all closes all transports."""
        with patch.object(ManagedTransport, "connect", new_callable=AsyncMock):
            await manager.get_transport(session)

        with patch.object(ManagedTransport, "close", new_callable=AsyncMock) as mock_close:
            await manager.close_all()

        mock_close.assert_called()
        assert len(manager._transports) == 0


class TestConnectionModes:
    """Tests for different connection modes."""

    @pytest.fixture
    def manager(self):
        return ConnectionManager()

    def test_connection_id_session_mode(self, manager):
        """Test connection ID generation for session mode."""
        session = FuzzSession(
            id="test-session",
            protocol="test",
            target_host="localhost",
            target_port=9999,
            status=FuzzSessionStatus.IDLE,
            connection_mode="session",
        )

        conn_id = manager._get_connection_id(session)
        assert conn_id == "test-session"

    def test_connection_id_per_stage_mode(self, manager):
        """Test connection ID generation for per_stage mode."""
        session = FuzzSession(
            id="test-session",
            protocol="test",
            target_host="localhost",
            target_port=9999,
            status=FuzzSessionStatus.IDLE,
            connection_mode="per_stage",
            current_stage="bootstrap",
        )

        conn_id = manager._get_connection_id(session)
        assert conn_id == "test-session:bootstrap"

    def test_connection_id_per_test_mode(self, manager):
        """Test connection ID generation for per_test mode."""
        session = FuzzSession(
            id="test-session",
            protocol="test",
            target_host="localhost",
            target_port=9999,
            status=FuzzSessionStatus.IDLE,
            connection_mode="per_test",
        )

        conn_id1 = manager._get_connection_id(session)
        conn_id2 = manager._get_connection_id(session)

        # per_test generates unique IDs
        assert conn_id1 != conn_id2
        assert conn_id1.startswith("test-session:")
