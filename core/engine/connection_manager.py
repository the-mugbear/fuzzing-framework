"""
Connection Manager - Manages persistent connections for orchestrated sessions.

Provides:
- Persistent TCP/UDP transports with connect/send/recv pattern
- ManagedTransport wrapper with health tracking and statistics
- ConnectionManager for session-scoped transport lifecycle
- Send coordination via mutex for concurrent heartbeat/fuzz traffic
- Response demultiplexing strategies (sequential, tagged, type-based)
"""
from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, Optional, TYPE_CHECKING

import structlog

from core.config import settings
from core.exceptions import (
    TransportError,
    ConnectionRefusedError as FuzzerConnectionRefusedError,
    ConnectionTimeoutError,
    SendError,
    ReceiveError,
    ReceiveTimeoutError,
)
from core.models import FuzzSession, TestCaseResult, TransportProtocol

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()


class ConnectionAbortError(Exception):
    """Raised when connection cannot be established after max retries."""
    pass


@dataclass
class PendingRequest:
    """Tracks a request awaiting a response for demux routing."""

    timeout_ms: Optional[int] = None
    correlation_key: Any = None
    # Future is created lazily to avoid event loop issues at instantiation time
    _future: Optional[asyncio.Future] = field(default=None, repr=False)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def future(self) -> asyncio.Future:
        """Get the future, creating it lazily if needed."""
        if self._future is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
            self._future = loop.create_future()
        return self._future

    async def wait(self) -> bytes:
        """Wait for the response with optional timeout."""
        timeout = self.timeout_ms / 1000 if self.timeout_ms else None
        try:
            return await asyncio.wait_for(self.future, timeout=timeout)
        except asyncio.TimeoutError:
            raise ReceiveTimeoutError("Response timeout waiting for pending request")

    def resolve(self, data: bytes) -> None:
        """Resolve this request with response data."""
        if not self.future.done():
            self.future.set_result(data)

    def fail(self, error: Exception) -> None:
        """Fail this request with an error."""
        if not self.future.done():
            self.future.set_exception(error)


class PersistentTCPTransport:
    """
    TCP transport with persistent connection support.

    Unlike the base TCPTransport which creates a new connection per
    send_and_receive call, this maintains a long-lived connection
    with separate connect/send/recv methods.
    """

    def __init__(self, host: str, port: int, timeout_ms: int):
        self.host = host
        self.port = port
        self.timeout_sec = timeout_ms / 1000.0

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and self._writer is not None

    async def connect(self) -> None:
        """Establish persistent TCP connection."""
        if self._connected:
            return

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout_sec,
            )
            self._connected = True
            logger.debug(
                "persistent_tcp_connected",
                host=self.host,
                port=self.port,
            )
        except asyncio.TimeoutError:
            raise ConnectionTimeoutError(
                f"Connection timeout to {self.host}:{self.port}",
                details={"timeout_sec": self.timeout_sec},
            )
        except ConnectionRefusedError as e:
            raise FuzzerConnectionRefusedError(
                f"Connection refused by {self.host}:{self.port}",
                details={"error": str(e)},
            )
        except OSError as e:
            raise TransportError(
                f"Failed to connect to {self.host}:{self.port}: {e}"
            )

    async def send(self, data: bytes) -> None:
        """Send data on the persistent connection."""
        if not self._connected or self._writer is None:
            raise TransportError("Not connected")

        try:
            self._writer.write(data)
            await self._writer.drain()
        except Exception as e:
            self._connected = False
            raise SendError(
                f"Failed to send data to {self.host}:{self.port}",
                details={"error": str(e), "data_size": len(data)},
            )

    async def recv(self, timeout_ms: Optional[int] = None) -> bytes:
        """
        Receive data from the persistent connection.

        Reads available data up to max_response_bytes or until timeout.
        """
        if not self._connected or self._reader is None:
            raise TransportError("Not connected")

        timeout = (timeout_ms / 1000) if timeout_ms else self.timeout_sec
        max_bytes = settings.max_response_bytes

        try:
            # Read with timeout
            data = await asyncio.wait_for(
                self._reader.read(max_bytes),
                timeout=timeout,
            )

            if not data:
                # Connection closed by peer
                self._connected = False
                raise ReceiveError("Connection closed by peer")

            return data

        except asyncio.TimeoutError:
            raise ReceiveTimeoutError(
                f"Receive timeout from {self.host}:{self.port}"
            )

    async def send_and_receive(
        self,
        data: bytes,
        timeout_ms: Optional[int] = None,
    ) -> bytes:
        """
        Combined send and receive for request-response pattern.

        Maintains connection between calls unlike base TCPTransport.
        """
        await self.send(data)
        return await self.recv(timeout_ms)

    async def cleanup(self) -> None:
        """Close the persistent connection."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                logger.warning(
                    "persistent_tcp_close_error",
                    host=self.host,
                    port=self.port,
                    error=str(e),
                )
        self._reader = None
        self._writer = None
        self._connected = False
        logger.debug(
            "persistent_tcp_closed",
            host=self.host,
            port=self.port,
        )


class ManagedTransport:
    """
    Wrapper around transport with persistent connection support.

    Extends the transport with:
    - Health tracking and statistics
    - Send coordination via mutex
    - Response demultiplexing for shared connections
    - Unsolicited message handling
    """

    def __init__(
        self,
        host: str,
        port: int,
        timeout_ms: int,
        demux_config: Optional[Dict[str, Any]] = None,
        transport_type: TransportProtocol = TransportProtocol.TCP,
    ):
        self.host = host
        self.port = port
        self.timeout_ms = timeout_ms
        self.demux_config = demux_config or {"strategy": "sequential"}
        self.transport_type = transport_type

        # Underlying transport
        self._transport: Optional[PersistentTCPTransport] = None

        # Connection state
        self.connected: bool = False
        self.healthy: bool = True

        # Statistics
        self.created_at: Optional[datetime] = None
        self.last_send: Optional[datetime] = None
        self.last_recv: Optional[datetime] = None
        self.bytes_sent: int = 0
        self.bytes_received: int = 0
        self.send_count: int = 0
        self.recv_count: int = 0

        # Send coordination
        self._send_lock: asyncio.Lock = asyncio.Lock()

        # Demux state (for reader loop mode)
        self._pending_requests: Deque[PendingRequest] = deque()
        self._pending_by_key: Dict[Any, PendingRequest] = {}
        self._unsolicited_queue: asyncio.Queue = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task] = None
        self._stop_reader: asyncio.Event = asyncio.Event()

        # Mode: 'simple' uses send_and_receive, 'reader_loop' uses background reader
        self._mode = "simple"

    async def connect(self) -> None:
        """Establish persistent connection."""
        if self.connected:
            return

        if self.transport_type == TransportProtocol.TCP:
            self._transport = PersistentTCPTransport(
                self.host, self.port, self.timeout_ms
            )
        else:
            # UDP doesn't support persistent connections (connectionless protocol)
            logger.error(
                "udp_persistent_not_supported",
                host=self.host,
                port=self.port,
                message="UDP does not support persistent connections. Use per_test connection mode.",
            )
            raise TransportError(
                "UDP does not support persistent connections. "
                "Set connection.mode to 'per_test' for UDP protocols."
            )

        await self._transport.connect()
        self.connected = True
        self.healthy = True
        self.created_at = datetime.utcnow()

        logger.info(
            "managed_transport_connected",
            host=self.host,
            port=self.port,
        )

    async def send(self, data: bytes) -> None:
        """
        Send data on persistent connection with mutex coordination.

        The mutex prevents interleaving between heartbeat and fuzz traffic.
        """
        if not self.connected:
            raise TransportError("Not connected")

        async with self._send_lock:
            try:
                await self._transport.send(data)
                self.last_send = datetime.utcnow()
                self.bytes_sent += len(data)
                self.send_count += 1
            except Exception as e:
                self.healthy = False
                raise

    async def recv(self, timeout_ms: Optional[int] = None) -> bytes:
        """
        Receive data from persistent connection.

        In simple mode, directly reads from transport.
        In reader_loop mode, waits for dispatched response.
        """
        if not self.connected:
            raise TransportError("Not connected")

        if self._mode == "simple":
            data = await self._transport.recv(timeout_ms)
            self.last_recv = datetime.utcnow()
            self.bytes_received += len(data)
            self.recv_count += 1
            return data
        else:
            # Reader loop mode - create pending request and wait
            request = PendingRequest(timeout_ms=timeout_ms)
            self._register_pending(request)
            return await request.wait()

    async def send_and_receive(
        self,
        data: bytes,
        timeout_ms: Optional[int] = None,
    ) -> bytes:
        """
        Combined send and receive with mutex coordination.

        This is the primary method for request-response exchanges.
        """
        if not self.connected:
            raise TransportError("Not connected")

        async with self._send_lock:
            try:
                await self._transport.send(data)
                self.last_send = datetime.utcnow()
                self.bytes_sent += len(data)
                self.send_count += 1

                response = await self._transport.recv(timeout_ms)
                self.last_recv = datetime.utcnow()
                self.bytes_received += len(response)
                self.recv_count += 1

                return response

            except ReceiveTimeoutError:
                # Timeout is not necessarily unhealthy - target may be slow
                raise
            except Exception as e:
                self.healthy = False
                raise

    async def close(self) -> None:
        """Close the persistent connection."""
        # Stop reader loop if running
        if self._reader_task:
            self._stop_reader.set()
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        # Fail pending requests
        for request in self._pending_requests:
            request.fail(TransportError("Connection closed"))
        self._pending_requests.clear()

        for request in self._pending_by_key.values():
            request.fail(TransportError("Connection closed"))
        self._pending_by_key.clear()

        # Close transport
        if self._transport:
            await self._transport.cleanup()
            self._transport = None

        self.connected = False
        self.healthy = False

        logger.info(
            "managed_transport_closed",
            host=self.host,
            port=self.port,
            bytes_sent=self.bytes_sent,
            bytes_received=self.bytes_received,
        )

    def _register_pending(self, request: PendingRequest) -> None:
        """Register a pending request for response dispatch."""
        strategy = self.demux_config.get("strategy", "sequential")
        if strategy == "sequential":
            self._pending_requests.append(request)
        else:
            key = request.correlation_key
            self._pending_by_key[key] = request

    def _dispatch_response(self, data: bytes) -> None:
        """Dispatch a response to the correct pending request."""
        strategy = self.demux_config.get("strategy", "sequential")

        if strategy == "sequential":
            if self._pending_requests:
                req = self._pending_requests.popleft()
                req.resolve(data)
                return

        elif strategy == "tagged":
            # Extract correlation key from response
            key = self._extract_correlation_key(data)
            req = self._pending_by_key.pop(key, None)
            if req:
                req.resolve(data)
                return

        elif strategy == "type_based":
            # Match by message type
            key = self._extract_message_type(data)
            req = self._pending_by_key.pop(key, None)
            if req:
                req.resolve(data)
                return

        # Unsolicited response handling
        handler = self.demux_config.get("unsolicited_handler", "log")
        if handler == "queue":
            self._unsolicited_queue.put_nowait(data)
        elif handler == "log":
            logger.warning(
                "unsolicited_response",
                size=len(data),
                preview=data[:32].hex(),
            )
        # "ignore" does nothing

    def _extract_correlation_key(self, data: bytes) -> Any:
        """Extract correlation key from response for tagged demux."""
        field = self.demux_config.get("correlation_field")
        if not field:
            return None
        # Would need parser to extract - for now return None
        # Full implementation requires response_model parsing
        return None

    def _extract_message_type(self, data: bytes) -> Any:
        """Extract message type from response for type-based demux."""
        # Simple implementation - first byte as type
        if data:
            return data[0]
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get transport statistics."""
        return {
            "connected": self.connected,
            "healthy": self.healthy,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_send": self.last_send.isoformat() if self.last_send else None,
            "last_recv": self.last_recv.isoformat() if self.last_recv else None,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "send_count": self.send_count,
            "recv_count": self.recv_count,
        }


class ConnectionManager:
    """
    Manages persistent transports with send coordination.

    Supports three connection modes:
    - per_test: New connection for each test (current behavior)
    - per_stage: Connection persists within a stage
    - session: Single connection across all stages

    Uses ManagedTransport to provide:
    - Health tracking
    - Send coordination (mutex for heartbeat)
    - Reconnect logic with optional re-bootstrap
    """

    def __init__(self):
        self._transports: Dict[str, ManagedTransport] = {}
        self._connection_configs: Dict[str, Dict[str, Any]] = {}

    def set_connection_config(
        self,
        session_id: str,
        config: Dict[str, Any],
    ) -> None:
        """Set connection configuration for a session."""
        self._connection_configs[session_id] = config

    def get_connection_config(self, session_id: str) -> Dict[str, Any]:
        """Get connection configuration for a session."""
        return self._connection_configs.get(session_id, {})

    async def get_transport(
        self,
        session: FuzzSession,
        use_replay_transport: bool = False,
    ) -> ManagedTransport:
        """
        Get or create managed transport for session.

        Creates new transport if:
        - No transport exists
        - Existing transport is unhealthy
        - Connection mode is per_test (always new)

        Args:
            session: The fuzzing session
            use_replay_transport: If True and a replay transport is registered,
                                  use it instead of creating/caching a new one.
                                  This prevents replay from hijacking active sessions.
        """
        # Check for registered replay transport if explicitly requested
        if use_replay_transport:
            replay_id = f"replay:{session.id}"
            if replay_id in self._transports:
                return self._transports[replay_id]

        conn_id = self._get_connection_id(session)
        config = self._connection_configs.get(session.id, {})
        mode = config.get("mode", session.connection_mode)

        # per_test always creates new connection
        if mode == "per_test":
            transport = await self._create_transport(session, config)
            return transport

        # Check for existing healthy transport
        if conn_id in self._transports:
            transport = self._transports[conn_id]
            if transport.connected and transport.healthy:
                return transport
            else:
                # Clean up unhealthy transport
                await transport.close()
                del self._transports[conn_id]

        # Create new transport
        transport = await self._create_transport(session, config)
        self._transports[conn_id] = transport

        return transport

    async def send_with_lock(
        self,
        session: FuzzSession,
        data: bytes,
        timeout_ms: Optional[int] = None,
    ) -> bytes:
        """
        Send data with transport lock.

        Prevents heartbeat and fuzz loop from interleaving sends.
        Uses the mutex inside ManagedTransport.

        For per_test mode, creates and closes transport after use to avoid leaks.
        For persistent modes, reuses cached transport.

        Args:
            session: The fuzzing session
            data: Data to send
            timeout_ms: Timeout for response

        Returns:
            Response bytes
        """
        # Check if we're in per_test mode (ephemeral connections)
        config = self._connection_configs.get(session.id, {})
        mode = config.get("mode", session.connection_mode)
        is_per_test = mode == "per_test"

        transport = await self.get_transport(session)
        try:
            return await transport.send_and_receive(
                data,
                timeout_ms or session.timeout_per_test_ms,
            )
        finally:
            # Close transport in per_test mode to avoid socket leaks
            if is_per_test:
                await transport.close()

    async def reconnect(
        self,
        session: FuzzSession,
        rebootstrap: bool = False,
    ) -> bool:
        """
        Reconnect a dropped connection.

        Args:
            session: The fuzzing session
            rebootstrap: If True, signal that bootstrap stages should re-run

        Returns:
            True if rebootstrap is needed, False otherwise
        """
        config = self._connection_configs.get(session.id, {})
        on_drop = config.get("on_drop", {})
        max_reconnects = on_drop.get("max_reconnects", 5)
        backoff_ms = on_drop.get("backoff_ms", 1000)

        # Check reconnect limit
        if session.reconnect_count >= max_reconnects:
            raise ConnectionAbortError(
                f"Max reconnects ({max_reconnects}) exceeded for session {session.id}"
            )

        # Close existing transport
        conn_id = self._get_connection_id(session)
        if conn_id in self._transports:
            await self._transports[conn_id].close()
            del self._transports[conn_id]

        # Backoff
        if backoff_ms > 0:
            await asyncio.sleep(backoff_ms / 1000)

        # Create new transport
        transport = await self._create_transport(session, config)
        self._transports[conn_id] = transport
        session.reconnect_count += 1

        logger.info(
            "connection_reconnected",
            session_id=session.id,
            reconnect_count=session.reconnect_count,
            rebootstrap=rebootstrap,
        )

        return rebootstrap

    async def close_session(self, session_id: str) -> None:
        """Close all transports for a session."""
        to_remove = [
            conn_id for conn_id in self._transports
            if conn_id.startswith(session_id)
        ]

        for conn_id in to_remove:
            transport = self._transports.pop(conn_id)
            await transport.close()

        # Clean up config
        self._connection_configs.pop(session_id, None)

        logger.debug(
            "session_connections_closed",
            session_id=session_id,
            closed_count=len(to_remove),
        )

    async def close_all(self) -> None:
        """Close all managed transports."""
        for transport in self._transports.values():
            await transport.close()
        self._transports.clear()
        self._connection_configs.clear()

    def get_transport_stats(self, session: FuzzSession) -> Optional[Dict[str, Any]]:
        """Get statistics for session's transport."""
        conn_id = self._get_connection_id(session)
        transport = self._transports.get(conn_id)
        if transport:
            return transport.get_stats()
        return None

    async def _create_transport(
        self,
        session: FuzzSession,
        config: Dict[str, Any],
    ) -> ManagedTransport:
        """Create new managed transport for session."""
        demux_config = config.get("demux", {"strategy": "sequential"})
        transport_type = getattr(session, "transport", TransportProtocol.TCP)

        transport = ManagedTransport(
            host=session.target_host,
            port=session.target_port,
            timeout_ms=session.timeout_per_test_ms,
            demux_config=demux_config,
            transport_type=transport_type,
        )

        await transport.connect()
        return transport

    async def create_replay_transport(
        self,
        session: FuzzSession,
    ) -> ManagedTransport:
        """
        Create an isolated transport for replay operations.

        This transport is NOT cached and should be closed by the caller
        when replay is complete. Use this instead of get_transport()
        for replay to avoid affecting the main session's connection.

        Args:
            session: The fuzzing session

        Returns:
            A new ManagedTransport instance (not cached)
        """
        transport_type = getattr(session, "transport", TransportProtocol.TCP)

        transport = ManagedTransport(
            host=session.target_host,
            port=session.target_port,
            timeout_ms=session.timeout_per_test_ms,
            demux_config={"strategy": "sequential"},
            transport_type=transport_type,
        )

        await transport.connect()
        logger.debug(
            "replay_transport_created",
            session_id=session.id,
            host=session.target_host,
            port=session.target_port,
        )
        return transport

    def register_replay_transport(
        self,
        session_id: str,
        transport: ManagedTransport,
    ) -> str:
        """
        Register a replay transport so get_transport() returns it.

        This allows bootstrap and replay to share the same connection.
        Call unregister_replay_transport() when done.

        Args:
            session_id: The session ID
            transport: The replay transport to register

        Returns:
            The connection ID used for registration
        """
        # Use a special replay-prefixed connection ID
        connection_id = f"replay:{session_id}"
        self._transports[connection_id] = transport
        logger.debug(
            "replay_transport_registered",
            session_id=session_id,
            connection_id=connection_id,
        )
        return connection_id

    def unregister_replay_transport(self, session_id: str) -> None:
        """
        Unregister a replay transport (does not close it).

        Args:
            session_id: The session ID
        """
        connection_id = f"replay:{session_id}"
        self._transports.pop(connection_id, None)
        logger.debug(
            "replay_transport_unregistered",
            session_id=session_id,
        )

    def _get_connection_id(self, session: FuzzSession) -> str:
        """Generate connection ID based on session and connection mode."""
        config = self._connection_configs.get(session.id, {})
        mode = config.get("mode", session.connection_mode)

        if mode == "session":
            return session.id
        elif mode == "per_stage":
            return f"{session.id}:{session.current_stage}"
        else:  # per_test
            return f"{session.id}:{uuid.uuid4()}"


# Global connection manager instance
connection_manager = ConnectionManager()
