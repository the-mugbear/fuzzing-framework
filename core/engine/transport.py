"""
Transport Abstraction Layer

Provides pluggable transport implementations for sending test cases to targets.
Supports TCP, UDP, and can be extended for custom transports (HTTP, gRPC, etc).
"""
import asyncio
import structlog
from abc import ABC, abstractmethod
from typing import Optional, Tuple

from core.config import settings
from core.exceptions import (
    TransportError,
    ConnectionRefusedError,
    ConnectionTimeoutError,
    SendError,
    ReceiveError,
    ReceiveTimeoutError,
)
from core.models import TestCaseResult

logger = structlog.get_logger()


class Transport(ABC):
    """
    Abstract base class for all transport implementations.

    Transports handle the actual network communication with targets.
    Each transport type implements its own connection, send, and receive logic.
    """

    def __init__(self, host: str, port: int, timeout_ms: int):
        """
        Initialize transport.

        Args:
            host: Target hostname or IP
            port: Target port
            timeout_ms: Timeout in milliseconds
        """
        self.host = host
        self.port = port
        self.timeout_sec = timeout_ms / 1000.0

    @abstractmethod
    async def send_and_receive(
        self, data: bytes
    ) -> Tuple[TestCaseResult, Optional[bytes]]:
        """
        Send data to target and receive response.

        Args:
            data: Binary test case data to send

        Returns:
            Tuple of (result, response_bytes)
            - result: TestCaseResult enum (PASS, CRASH, HANG, etc)
            - response_bytes: Response from target, or None if no response

        Raises:
            TransportError: On communication failures
        """
        pass

    @abstractmethod
    async def cleanup(self):
        """
        Cleanup transport resources.

        Called when test execution completes or session ends.
        Should close connections and release resources.
        """
        pass


class TCPTransport(Transport):
    """
    TCP stream transport implementation.

    Establishes TCP connection, sends data, reads response with timeout.
    """

    async def send_and_receive(
        self, data: bytes
    ) -> Tuple[TestCaseResult, Optional[bytes]]:
        """Send test case over TCP and read response."""
        reader: Optional[asyncio.StreamReader] = None
        writer: Optional[asyncio.StreamWriter] = None

        try:
            # Establish connection
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=self.timeout_sec
                )
            except asyncio.TimeoutError:
                raise ConnectionTimeoutError(
                    f"Connection timeout to {self.host}:{self.port}",
                    details={"timeout_sec": self.timeout_sec}
                )
            except ConnectionRefusedError as e:
                raise ConnectionRefusedError(
                    f"Connection refused by {self.host}:{self.port}",
                    details={"error": str(e)}
                )

            # Send test data
            try:
                writer.write(data)
                await writer.drain()
            except Exception as e:
                raise SendError(
                    f"Failed to send data to {self.host}:{self.port}",
                    details={"error": str(e), "data_size": len(data)}
                )

            # Read response
            try:
                response = await self._read_response(reader, self.timeout_sec)
                return TestCaseResult.PASS, response
            except asyncio.TimeoutError:
                logger.debug(
                    "target_timeout",
                    host=self.host,
                    port=self.port,
                    phase="read"
                )
                return TestCaseResult.HANG, None

        finally:
            # Cleanup
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception as e:
                    logger.warning(
                        "tcp_writer_close_failed",
                        host=self.host,
                        port=self.port,
                        error=str(e),
                        error_type=type(e).__name__
                    )

    async def _read_response(
        self, reader: asyncio.StreamReader, timeout: float
    ) -> bytes:
        """Read response with timeout and size limits."""
        chunks: list[bytes] = []
        total = 0
        max_bytes = settings.max_response_bytes

        while total < max_bytes:
            read_size = min(settings.tcp_buffer_size, max_bytes - total)
            try:
                chunk = await asyncio.wait_for(reader.read(read_size), timeout=timeout)
            except asyncio.TimeoutError:
                if not chunks:
                    raise
                logger.debug("response_read_timeout_partial", received=total)
                break

            if not chunk:
                break

            chunks.append(chunk)
            total += len(chunk)

        return b"".join(chunks)

    async def cleanup(self):
        """TCP cleanup handled in send_and_receive finally block."""
        pass


class UDPTransport(Transport):
    """
    UDP datagram transport implementation.

    Sends UDP datagram and waits for response with timeout.
    """

    async def send_and_receive(
        self, data: bytes
    ) -> Tuple[TestCaseResult, Optional[bytes]]:
        """Send test case over UDP and read response."""
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[bytes] = loop.create_future()
        max_bytes = settings.max_response_bytes

        class _UDPClient(asyncio.DatagramProtocol):
            def __init__(self):
                self.transport: Optional[asyncio.transports.DatagramTransport] = None

            def connection_made(self, transport: asyncio.BaseTransport) -> None:
                self.transport = transport  # type: ignore
                self.transport.sendto(data)

            def datagram_received(self, received_data: bytes, addr: tuple) -> None:
                if not response_future.done():
                    response_future.set_result(received_data[:max_bytes])

            def error_received(self, exc: Optional[Exception]) -> None:
                if not response_future.done():
                    response_future.set_exception(
                        exc or TransportError("udp_error")
                    )

        transport: Optional[asyncio.transports.DatagramTransport] = None
        try:
            transport, _ = await loop.create_datagram_endpoint(
                _UDPClient,
                remote_addr=(self.host, self.port),
            )

            response = await asyncio.wait_for(
                response_future,
                timeout=self.timeout_sec,
            )
            return TestCaseResult.PASS, response

        except asyncio.TimeoutError:
            logger.debug(
                "target_timeout",
                host=self.host,
                port=self.port,
                phase="udp"
            )
            return TestCaseResult.HANG, None

        except (ConnectionRefusedError, OSError) as exc:
            logger.error(
                "udp_target_unreachable",
                host=self.host,
                port=self.port,
                error=str(exc),
            )
            raise ConnectionRefusedError(
                f"UDP target unreachable {self.host}:{self.port}",
                details={"error": str(exc)}
            )

        finally:
            if transport:
                try:
                    transport.close()
                except Exception as e:
                    logger.warning(
                        "udp_transport_close_failed",
                        host=self.host,
                        port=self.port,
                        error=str(e),
                        error_type=type(e).__name__
                    )

    async def cleanup(self):
        """UDP cleanup handled in send_and_receive finally block."""
        pass


class TransportFactory:
    """
    Factory for creating transport instances.

    Determines appropriate transport based on protocol or session configuration.
    """

    @staticmethod
    def create_transport(protocol: str, host: str, port: int, timeout_ms: int) -> Transport:
        """
        Create appropriate transport for the given protocol.

        Args:
            protocol: Protocol name (determines transport type)
            host: Target host
            port: Target port
            timeout_ms: Timeout in milliseconds

        Returns:
            Transport instance (TCP or UDP)

        Note: Currently defaults to TCP. Protocol-specific transport
        selection can be added in the future.
        """
        # TODO: Add protocol metadata for transport selection
        # For now, default to TCP (most protocols use TCP)
        return TCPTransport(host, port, timeout_ms)

    @staticmethod
    def create_tcp_transport(host: str, port: int, timeout_ms: int) -> TCPTransport:
        """Create TCP transport explicitly."""
        return TCPTransport(host, port, timeout_ms)

    @staticmethod
    def create_udp_transport(host: str, port: int, timeout_ms: int) -> UDPTransport:
        """Create UDP transport explicitly."""
        return UDPTransport(host, port, timeout_ms)
