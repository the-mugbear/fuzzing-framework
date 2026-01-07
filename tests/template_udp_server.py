"""
UDP Protocol Server Template

This is a template for implementing custom UDP protocol servers for fuzzing
verification and validation testing. Copy this file and customize it for your
specific protocol.

USAGE:
    python tests/template_udp_server.py --host 0.0.0.0 --port 9999

KEY FEATURES:
    - Simple datagram-based communication
    - No connection state management
    - Protocol parser integration
    - Response crafting examples
    - Extensive documentation for customization

UDP vs TCP CONSIDERATIONS:
    - UDP is connectionless (no handshake/teardown)
    - Each datagram is independent
    - No guaranteed delivery or ordering
    - No flow control or congestion management
    - Simpler to implement but less reliable
    - Good for: stateless protocols, multicast, low-latency apps

CUSTOMIZATION CHECKLIST:
    [ ] Update PROTOCOL_NAME constant
    [ ] Import your protocol plugin from core/plugins/
    [ ] Customize MAX_DATAGRAM_SIZE if needed
    [ ] Implement _process_message() with your protocol logic
    [ ] Customize _build_response() for your response format
    [ ] Consider if your protocol needs session/state tracking
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# Ensure the repository root is on sys.path when running inside containers
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

# ============================================================================
# CUSTOMIZATION POINT 1: Import your protocol plugin
# ============================================================================
# Replace this with your actual protocol plugin import
# Example: from core.plugins import my_udp_protocol
#
# For this template, we'll use simple_tcp as a basic example
# (even though it's called simple_tcp, the logic works for UDP too)
from core.engine.protocol_parser import ProtocolParser
try:
    from core.plugins import simple_tcp as example_protocol
except ImportError:
    # Fallback if simple_tcp doesn't exist
    from core.plugins import feature_showcase as example_protocol

# Protocol name for logging
PROTOCOL_NAME = "Example UDP Protocol"  # Change to your protocol name

# ============================================================================
# CUSTOMIZATION POINT 2: Maximum datagram size
# ============================================================================
# UDP datagrams are limited by the MTU (Maximum Transmission Unit).
# Common values:
#   - 576 bytes: Safe minimum (IPv4 minimum reassembly buffer)
#   - 1472 bytes: Ethernet MTU (1500) - IP header (20) - UDP header (8)
#   - 8192 bytes: Common for local/internal networks
#   - 65507 bytes: Theoretical UDP maximum
#
# For fuzzing, 8192 is a good default that handles most protocols
# while avoiding fragmentation on most networks.
MAX_DATAGRAM_SIZE = 8192


class TemplateUdpServer:
    """
    Template UDP server for protocol fuzzing validation.

    UDP servers are simpler than TCP servers because:
    1. No connection state - each datagram is independent
    2. No deadlock issues - no connection to close
    3. No handshake overhead
    4. Single recv() per message (up to MAX_DATAGRAM_SIZE)

    However, UDP has limitations:
    - No delivery guarantee
    - No ordering guarantee
    - No automatic retransmission
    - Datagrams can be duplicated or lost
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9999) -> None:
        """
        Initialize the UDP server.

        Args:
            host: Interface to bind to (0.0.0.0 for all interfaces)
            port: Port number to listen on
        """
        self.host = host
        self.port = port
        self.running = False
        self.server_socket: Optional[socket.socket] = None
        self._color_enabled = sys.stdout.isatty()

        # ====================================================================
        # CUSTOMIZATION POINT 3: Initialize protocol parsers
        # ====================================================================
        # The ProtocolParser uses the same data_model from your plugin,
        # ensuring the server and fuzzer stay in sync.
        self.request_parser = ProtocolParser(example_protocol.data_model)

        # If your protocol has a separate response format, add a response parser
        # For simple echo protocols, you might use the same parser for both
        try:
            self.response_parser = ProtocolParser(example_protocol.response_model)
        except AttributeError:
            # No separate response model - use request model
            self.response_parser = self.request_parser

        # ====================================================================
        # CUSTOMIZATION POINT 4: Session/state tracking (optional)
        # ====================================================================
        # UDP is stateless, but your protocol might need to track state
        # across multiple datagrams. For example:
        # - Session tokens
        # - Sequence numbers
        # - Client addresses
        #
        # Use a dict keyed by (client_ip, client_port) tuple
        self.sessions: Dict[Tuple[str, int], Dict[str, any]] = {}
        self.message_counter = 0

    def start(self) -> None:
        """Start the UDP server and listen for datagrams."""
        # Create UDP socket (SOCK_DGRAM)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Allow address reuse (helpful for quick restarts during development)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Bind to the specified address and port
        self.server_socket.bind((self.host, self.port))
        self.running = True

        self._print_banner()
        self._log("info", f"{PROTOCOL_NAME} UDP server listening on {self.host}:{self.port}")
        self._log("info", f"Max datagram size: {MAX_DATAGRAM_SIZE} bytes")

        try:
            while self.running:
                try:
                    # ========================================================
                    # UDP MESSAGE RECEPTION
                    # ========================================================
                    # recvfrom() receives one complete datagram and returns:
                    # - data: The datagram bytes
                    # - addr: Tuple of (client_ip, client_port)
                    #
                    # Unlike TCP:
                    # - No connection handshake needed
                    # - No need to track connection state
                    # - Each recvfrom() gets exactly one datagram
                    # - No partial reads (unlike TCP's stream nature)
                    data, addr = self.server_socket.recvfrom(MAX_DATAGRAM_SIZE)

                    if data:
                        # Process the datagram in the main thread
                        # (UDP is simple enough that threading is often unnecessary)
                        #
                        # If you need concurrency for heavy processing, you can:
                        # - Spawn a thread per datagram
                        # - Use a thread pool
                        # - Use asyncio
                        self.handle_datagram(data, addr)

                except socket.timeout:
                    # If you set a timeout with socket.settimeout(),
                    # this exception is raised when it expires
                    continue
                except Exception as exc:
                    if self.running:
                        self._log("error", f"Receive error: {exc}")
        except KeyboardInterrupt:
            self._log("info", "Shutting down...")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the server gracefully."""
        self.running = False
        if self.server_socket:
            self.server_socket.close()

    def handle_datagram(self, data: bytes, addr: Tuple[str, int]) -> None:
        """
        Handle a single UDP datagram.

        This is much simpler than TCP because:
        1. No connection management
        2. No framing issues - each datagram is one message
        3. No deadlock concerns
        4. No need to read in chunks

        Args:
            data: The datagram bytes
            addr: Client address tuple (ip, port)
        """
        self.message_counter += 1
        client_ip, client_port = addr

        self._log("info", f"[msg#{self.message_counter}] Received {len(data)} bytes from {client_ip}:{client_port}")

        try:
            # ================================================================
            # STEP 1: Parse the datagram
            # ================================================================
            try:
                fields = self.request_parser.parse(data)
                self._log("debug", f"Parsed message with {len(fields)} fields")
            except ValueError as exc:
                self._log("error", f"Parse error: {exc}")
                # Send error response
                error_response = self._build_error_response(
                    f"Parse error: {exc}".encode()
                )
                self._send_response(error_response, addr)
                return

            # ================================================================
            # STEP 2: Process message and craft response
            # ================================================================
            response = self._process_message(fields, addr)

            # ================================================================
            # STEP 3: Send response
            # ================================================================
            # UDP response is sent with sendto(), which includes the
            # destination address
            self._send_response(response, addr)

        except Exception as exc:
            self._log("error", f"Error handling datagram: {exc}")
            # Optionally send error response
            try:
                error_response = self._build_error_response(str(exc).encode())
                self._send_response(error_response, addr)
            except Exception:
                pass  # If we can't send error response, just log it

    def _send_response(self, response: bytes, addr: Tuple[str, int]) -> None:
        """
        Send a UDP response datagram.

        Args:
            response: Response bytes to send
            addr: Destination address (ip, port)
        """
        try:
            # Check if response fits in a single datagram
            if len(response) > MAX_DATAGRAM_SIZE:
                self._log("warning", f"Response size {len(response)} exceeds MAX_DATAGRAM_SIZE {MAX_DATAGRAM_SIZE}")
                # You have several options here:
                # 1. Truncate the response
                # 2. Send an error instead
                # 3. Fragment manually (complex!)
                # 4. Increase MAX_DATAGRAM_SIZE (risk fragmentation)
                #
                # For this template, we'll truncate and warn
                response = response[:MAX_DATAGRAM_SIZE]

            # Send the response datagram
            bytes_sent = self.server_socket.sendto(response, addr)
            self._log("info", f"Sent {bytes_sent} bytes to {addr[0]}:{addr[1]}")

        except Exception as exc:
            self._log("error", f"Failed to send response: {exc}")

    def _process_message(self, fields: Dict[str, any], addr: Tuple[str, int]) -> bytes:
        """
        Process a parsed message and craft a response.

        CUSTOMIZATION POINT 5: Message Processing Logic
        ================================================
        This is where you implement your protocol's business logic.

        For UDP protocols, consider:
        - Idempotency: Can you handle duplicate datagrams safely?
        - Sequencing: Do you need to track message order?
        - Session state: Do you need to track state per client?

        Args:
            fields: Parsed message fields from ProtocolParser
            addr: Client address tuple (ip, port)

        Returns:
            Response bytes to send back
        """
        client_ip, client_port = addr

        # ====================================================================
        # EXAMPLE IMPLEMENTATION
        # ====================================================================
        # This is a simple echo-style implementation.
        # REPLACE with your protocol's logic!

        # Get session state (create if doesn't exist)
        session_key = (client_ip, client_port)
        if session_key not in self.sessions:
            self.sessions[session_key] = {
                "messages_received": 0,
                "first_seen": datetime.now()
            }

        session = self.sessions[session_key]
        session["messages_received"] += 1
        session["last_seen"] = datetime.now()

        # Extract fields (customize for your protocol!)
        magic = fields.get("magic", b"")
        payload = fields.get("payload", b"")

        # Validate magic header (example)
        if magic != b"STCP":  # Replace with your protocol's magic
            return self._build_error_response(
                f"Invalid magic: {magic!r}".encode()
            )

        # Log the message type or command
        self._log("info", f"Processing payload: {len(payload)} bytes")

        # Build response
        response_fields = {
            "magic": magic,  # Echo back the magic
            "status": 0x00,  # Success
            "payload": f"Echo: received {len(payload)} bytes (msg #{session['messages_received']})".encode()
        }

        return self._build_response(response_fields)

    def _build_response(self, fields: Dict[str, any]) -> bytes:
        """
        Build a response message.

        CUSTOMIZATION POINT 6: Response Format
        =======================================
        Use your response_parser to serialize response fields.

        Args:
            fields: Response fields dictionary

        Returns:
            Serialized response bytes
        """
        try:
            return self.response_parser.serialize(fields)
        except Exception as exc:
            self._log("error", f"Failed to serialize response: {exc}")
            # Return a minimal error response
            return b"ERROR: Failed to serialize response"

    def _build_error_response(self, error_msg: bytes) -> bytes:
        """
        Build an error response.

        Args:
            error_msg: Error message bytes

        Returns:
            Error response bytes
        """
        # For simple protocols, you might just return the error message
        # For complex protocols, use your response format
        error_fields = {
            "magic": b"ERR!",
            "status": 0xFF,  # Error status
            "payload": error_msg
        }

        try:
            return self._build_response(error_fields)
        except Exception:
            # If building structured response fails, return raw error
            return b"ERROR: " + error_msg

    # ========================================================================
    # Logging and Display Helpers
    # ========================================================================

    def _print_banner(self) -> None:
        """Print startup banner."""
        banner = f"""
{'='*70}
{PROTOCOL_NAME:^70}
UDP Protocol Server Template
{'='*70}
"""
        print(banner)

    def _log(self, level: str, message: str) -> None:
        """Log a message with level and timestamp."""
        # Skip debug logs unless you want verbose output
        if level == "debug":
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_colors = {
            "info": "\033[36m",     # Cyan
            "success": "\033[32m",  # Green
            "warning": "\033[33m",  # Yellow
            "error": "\033[31m",    # Red
            "debug": "\033[90m",    # Gray
        }
        reset = "\033[0m"

        if self._color_enabled:
            color = level_colors.get(level, "")
            print(f"[{timestamp}]{color}[{level.upper():7}]{reset} {message}")
        else:
            print(f"[{timestamp}][{level.upper():7}] {message}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description=f"{PROTOCOL_NAME} UDP Server Template",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run on default port 9999
  python tests/template_udp_server.py

  # Run on custom port
  python tests/template_udp_server.py --port 8888

  # Bind to specific interface
  python tests/template_udp_server.py --host 192.168.1.100 --port 9999

UDP-specific notes:
  - No connection state - each datagram is independent
  - No guaranteed delivery - datagrams may be lost
  - No ordering - datagrams may arrive out of order
  - No fragmentation handling at application level
  - Good for stateless protocols and low-latency requirements
        """
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host/interface to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9999,
        help="Port to listen on (default: 9999)"
    )
    parser.add_argument(
        "--max-datagram-size",
        type=int,
        default=MAX_DATAGRAM_SIZE,
        help=f"Maximum datagram size in bytes (default: {MAX_DATAGRAM_SIZE})"
    )

    args = parser.parse_args()

    # Update global max datagram size if specified
    global MAX_DATAGRAM_SIZE
    MAX_DATAGRAM_SIZE = args.max_datagram_size

    server = TemplateUdpServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
