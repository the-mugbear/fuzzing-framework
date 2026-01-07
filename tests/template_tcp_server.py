"""
TCP Protocol Server Template

This is a template for implementing custom TCP protocol servers for fuzzing
verification and validation testing. Copy this file and customize it for your
specific protocol.

USAGE:
    python tests/template_tcp_server.py --host 0.0.0.0 --port 9999

KEY FEATURES:
    - Intelligent message reading (avoids deadlock with fuzzer)
    - Protocol parser integration
    - Response crafting examples
    - Proper timeout handling
    - Extensive documentation for customization

CUSTOMIZATION CHECKLIST:
    [ ] Update PROTOCOL_NAME constant
    [ ] Import your protocol plugin from core/plugins/
    [ ] Customize _calculate_message_size() for your protocol's framing
    [ ] Implement _process_message() with your protocol logic
    [ ] Customize _build_response() for your response format
    [ ] Adjust timeouts based on your testing needs
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import threading
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
# Example: from core.plugins import my_protocol
#
# For this template, we'll use feature_showcase as an example
from core.engine.protocol_parser import ProtocolParser
from core.plugins import feature_showcase

# Protocol name for logging
PROTOCOL_NAME = "Feature Showcase"  # Change to your protocol name


class TemplateTcpServer:
    """
    Template TCP server for protocol fuzzing validation.

    This server demonstrates the CORRECT way to handle TCP connections from
    the fuzzer, avoiding common pitfalls like deadlocks and timeouts.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9999) -> None:
        """
        Initialize the TCP server.

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
        # CUSTOMIZATION POINT 2: Initialize protocol parsers
        # ====================================================================
        # The ProtocolParser uses the same data_model from your plugin,
        # ensuring the server and fuzzer stay in sync.
        #
        # Replace feature_showcase with your protocol plugin
        self.request_parser = ProtocolParser(feature_showcase.data_model)

        # If your protocol has a separate response format, add a response parser
        self.response_parser = ProtocolParser(feature_showcase.response_model)

        # Track any stateful session data (e.g., session tokens)
        self.sessions: Dict[int, Dict[str, any]] = {}
        self.message_counter = 0

    def start(self) -> None:
        """Start the TCP server and listen for connections."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True

        self._print_banner()
        self._log("info", f"{PROTOCOL_NAME} TCP server listening on {self.host}:{self.port}")

        try:
            while self.running:
                try:
                    # Accept client connections and spawn handler threads
                    client_sock, addr = self.server_socket.accept()
                    self._log("success", f"Connection from {addr[0]}:{addr[1]}")

                    # Handle each client in a separate thread
                    thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_sock, addr),
                        daemon=True
                    )
                    thread.start()
                except socket.timeout:
                    continue
                except Exception as exc:
                    if self.running:
                        self._log("error", f"Accept error: {exc}")
        except KeyboardInterrupt:
            self._log("info", "Shutting down...")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the server gracefully."""
        self.running = False
        if self.server_socket:
            self.server_socket.close()

    def handle_client(self, client_sock: socket.socket, addr: tuple) -> None:
        """
        Handle a single client connection.

        CRITICAL: This method demonstrates the CORRECT way to receive messages
        from the fuzzer without creating deadlocks.

        THE PROBLEM WITH NAIVE APPROACHES:
        -----------------------------------
        Many protocol servers use this pattern:

            while True:
                data = sock.recv(4096)
                if not data:  # Wait for client to close
                    break
                buffer += data

        This DEADLOCKS with the fuzzer because:
        1. Fuzzer sends data and KEEPS CONNECTION OPEN waiting for response
        2. Server waits for connection close before processing
        3. Both sides wait forever (until timeout)

        THE SOLUTION:
        -------------
        Read the message intelligently based on protocol structure:
        1. Read fixed header containing length fields
        2. Parse length fields to determine total message size
        3. Read remaining bytes until complete message received
        4. Process and respond IMMEDIATELY (don't wait for connection close)

        Args:
            client_sock: The client socket
            addr: Client address tuple (ip, port)
        """
        self._log_raw("")  # Blank line for readability
        self._log("success", f"Session started from {addr[0]}:{addr[1]}")
        buffer = b""

        try:
            # ================================================================
            # TIMEOUT CONFIGURATION
            # ================================================================
            # Set socket timeout for individual recv() calls.
            #
            # For verification/validation testing:
            #   - 0.5-1.0 seconds is ideal for local testing
            #   - Allows quick hang detection
            #   - Pair with fuzzer timeout of 1.5-2.0 seconds
            #
            # For production/network testing:
            #   - 3-5 seconds may be needed
            client_sock.settimeout(1.0)

            # ================================================================
            # STEP 1: Receive complete message
            # ================================================================
            # This is where you implement protocol-specific message framing.
            # The goal is to read exactly one complete message without waiting
            # for the client to close the connection.
            buffer = self._receive_complete_message(client_sock, addr)

            if not buffer:
                self._log("info", "Client closed without sending data")
                self._log_raw("")
                return

            # ================================================================
            # STEP 2: Parse the message
            # ================================================================
            try:
                fields = self.request_parser.parse(buffer)
                self._log("info", f"Parsed message: {len(buffer)} bytes")
            except ValueError as exc:
                self._log("error", f"Parse error: {exc}")
                # Send error response
                response = self._build_error_response(
                    f"Parse error: {exc}".encode()
                )
                client_sock.sendall(response)
                self._log_raw("")
                return

            # ================================================================
            # STEP 3: Process message and craft response
            # ================================================================
            response = self._process_message(fields, addr)

            # ================================================================
            # STEP 4: Send response immediately
            # ================================================================
            # Don't wait for client to close - respond right away!
            client_sock.sendall(response)
            self._log("info", f"Sent response: {len(response)} bytes")
            self._log_raw("")

        except socket.timeout:
            self._log("warning", "Client timed out")
            self._log_raw("")
        except Exception as exc:
            self._log("error", f"Unexpected error: {exc}")
            self._log_raw("")
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def _receive_complete_message(
        self, client_sock: socket.socket, addr: tuple
    ) -> bytes:
        """
        Receive a complete protocol message intelligently.

        This method implements protocol-specific message framing to read
        exactly one complete message without waiting for connection close.

        CUSTOMIZATION POINT 3: Message Framing
        =======================================
        You MUST customize this method for your protocol's framing mechanism.

        Common framing strategies:

        1. LENGTH-PREFIXED (most binary protocols):
           - Read fixed header containing length field
           - Parse length field
           - Read remaining bytes based on length
           - Example: HTTP/2, gRPC, most custom binary protocols

        2. DELIMITER-BASED (text protocols):
           - Read until you see delimiter (e.g., newline, null byte)
           - Example: HTTP/1.1 (headers), Redis, SMTP

        3. FIXED-SIZE MESSAGES:
           - If all messages are same size, just read that many bytes
           - Example: Some legacy protocols, simple packet formats

        4. COMPOUND (combination):
           - Read header to get multiple length fields
           - Calculate total size from multiple variable sections
           - Example: This template's implementation below

        Args:
            client_sock: Socket to read from
            addr: Client address for logging

        Returns:
            Complete message bytes
        """
        buffer = b""

        # ====================================================================
        # EXAMPLE IMPLEMENTATION: Length-prefixed protocol
        # ====================================================================
        # This example shows a protocol with:
        # - Fixed header (23 bytes) containing payload_len field
        # - Variable payload section
        # - metadata_len field after payload
        # - Variable metadata section
        # - Fixed trailing fields (9 bytes)
        #
        # REPLACE THIS with your protocol's framing logic!

        try:
            # STEP 1: Read minimum header to get first length field
            # For this example: 23 bytes to reach payload_len field
            #
            # For your protocol, calculate how many bytes you need to read
            # to get to the first length/size field.
            MIN_HEADER_SIZE = 23  # Customize for your protocol!

            while len(buffer) < MIN_HEADER_SIZE:
                chunk = client_sock.recv(MIN_HEADER_SIZE - len(buffer))
                if not chunk:
                    self._log("warning", f"Client closed after {len(buffer)} bytes")
                    return b""
                buffer += chunk

            # STEP 2: Calculate total message size
            # This is protocol-specific - customize for your needs!
            total_size = self._calculate_message_size(buffer, client_sock)

            # STEP 3: Read remaining bytes
            while len(buffer) < total_size:
                bytes_needed = total_size - len(buffer)
                chunk = client_sock.recv(min(bytes_needed, 4096))
                if not chunk:
                    self._log("warning", f"Client closed at {len(buffer)}/{total_size} bytes")
                    return b""
                buffer += chunk

            return buffer

        except struct.error as exc:
            self._log("error", f"Struct unpack error: {exc}")
            return b""

    def _calculate_message_size(
        self, initial_buffer: bytes, client_sock: socket.socket
    ) -> int:
        """
        Calculate the total message size from protocol headers.

        CUSTOMIZATION POINT 4: Message Size Calculation
        ================================================
        This is where you parse length fields from your protocol header
        to determine the total message size.

        Args:
            initial_buffer: Header bytes already read
            client_sock: Socket (in case you need to read more to get all length fields)

        Returns:
            Total message size in bytes
        """
        # ====================================================================
        # EXAMPLE: Feature Showcase protocol
        # ====================================================================
        # Message structure:
        #   0-22:   Fixed header (23 bytes)
        #   23-N:   Payload (length from offset 19-22)
        #   N+0-1:  metadata_len field (2 bytes)
        #   N+2-M:  Metadata (length from metadata_len)
        #   M+0-8:  Trailing fixed fields (9 bytes)
        #
        # REPLACE with your protocol's structure!

        buffer = initial_buffer

        # Parse payload_len (uint32 big-endian at offset 19)
        # Adjust offset and format for your protocol!
        payload_len = struct.unpack('>I', buffer[19:23])[0]

        # Read enough to get metadata_len field (comes after payload)
        bytes_needed = 23 + payload_len + 2
        while len(buffer) < bytes_needed:
            chunk = client_sock.recv(bytes_needed - len(buffer))
            if not chunk:
                raise ValueError("Connection closed while reading length fields")
            buffer += chunk

        # Parse metadata_len (uint16 big-endian after payload)
        metadata_offset = 23 + payload_len
        metadata_len = struct.unpack('>H', buffer[metadata_offset:metadata_offset+2])[0]

        # Calculate total: header + payload + metadata_len + metadata + trailing
        TRAILING_SIZE = 9  # Customize for your protocol
        total = 23 + payload_len + 2 + metadata_len + TRAILING_SIZE

        return total

    def _process_message(self, fields: Dict[str, any], addr: tuple) -> bytes:
        """
        Process a parsed message and craft a response.

        CUSTOMIZATION POINT 5: Message Processing Logic
        ================================================
        This is where you implement your protocol's business logic:
        - Validate the message fields
        - Update any stateful session data
        - Craft an appropriate response

        Args:
            fields: Parsed message fields from ProtocolParser
            addr: Client address

        Returns:
            Response bytes to send back
        """
        self.message_counter += 1

        # ====================================================================
        # EXAMPLE: Feature Showcase protocol logic
        # ====================================================================
        # This example shows message type dispatch and response crafting.
        # REPLACE with your protocol's logic!

        # Extract common fields
        magic = fields.get("magic")
        msg_type = fields.get("message_type")
        session_id = fields.get("session_id", 0)

        # Validate magic header
        if magic != b"SHOW":  # Replace with your protocol's magic
            return self._build_error_response(
                f"Invalid magic: {magic!r}".encode()
            )

        # Log the message
        self._log("info", f"[msg#{self.message_counter}] Processing message_type={msg_type}")

        # Dispatch based on message type
        # Customize this for your protocol's message types!
        if msg_type == 1:  # HANDSHAKE_REQUEST
            return self._handle_handshake(fields)
        elif msg_type == 2:  # DATA_STREAM
            return self._handle_data(fields)
        elif msg_type == 3:  # HEARTBEAT
            return self._handle_heartbeat(fields)
        else:
            return self._build_error_response(
                f"Unknown message type: {msg_type}".encode()
            )

    def _handle_handshake(self, fields: Dict[str, any]) -> bytes:
        """
        Handle handshake message.

        CUSTOMIZATION POINT 6: Handshake Logic
        =======================================
        Implement your protocol's handshake/initialization logic.
        """
        import secrets

        # Generate session token
        session_token = secrets.randbits(64)
        self.sessions[session_token] = {"state": "HANDSHAKE"}

        # Build response
        response_fields = {
            "status": 0x00,  # Success
            "session_token": session_token,
            "details": b"Handshake accepted"
        }

        return self._build_response(response_fields)

    def _handle_data(self, fields: Dict[str, any]) -> bytes:
        """Handle data message."""
        session_id = fields.get("session_id")
        payload = fields.get("payload", b"")

        # Validate session
        if session_id not in self.sessions:
            return self._build_error_response(b"Invalid session ID")

        # Update session state
        self.sessions[session_id]["state"] = "ESTABLISHED"

        # Build response
        response_fields = {
            "status": 0x00,
            "session_token": session_id,
            "details": f"Received {len(payload)} bytes".encode()
        }

        return self._build_response(response_fields)

    def _handle_heartbeat(self, fields: Dict[str, any]) -> bytes:
        """Handle heartbeat message."""
        response_fields = {
            "status": 0x00,
            "session_token": 0,
            "details": b"Heartbeat acknowledged"
        }
        return self._build_response(response_fields)

    def _build_response(self, fields: Dict[str, any]) -> bytes:
        """
        Build a response message.

        CUSTOMIZATION POINT 7: Response Format
        =======================================
        Use your response_parser to serialize response fields.

        Args:
            fields: Response fields dictionary

        Returns:
            Serialized response bytes
        """
        # Use the response parser to serialize fields
        return self.response_parser.serialize(fields)

    def _build_error_response(self, error_msg: bytes) -> bytes:
        """Build an error response."""
        error_fields = {
            "status": 0xFF,  # Error status
            "session_token": 0,
            "details": error_msg
        }
        return self._build_response(error_fields)

    # ========================================================================
    # Logging and Display Helpers
    # ========================================================================

    def _print_banner(self) -> None:
        """Print startup banner."""
        banner = f"""
{'='*70}
{PROTOCOL_NAME:^70}
TCP Protocol Server Template
{'='*70}
"""
        print(banner)

    def _log(self, level: str, message: str) -> None:
        """Log a message with level and timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_colors = {
            "info": "\033[36m",     # Cyan
            "success": "\033[32m",  # Green
            "warning": "\033[33m",  # Yellow
            "error": "\033[31m",    # Red
        }
        reset = "\033[0m"

        if self._color_enabled:
            color = level_colors.get(level, "")
            print(f"[{timestamp}]{color}[{level.upper():7}]{reset} {message}")
        else:
            print(f"[{timestamp}][{level.upper():7}] {message}")

    def _log_raw(self, message: str) -> None:
        """Log without formatting."""
        print(message)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description=f"{PROTOCOL_NAME} TCP Server Template",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run on default port 9999
  python tests/template_tcp_server.py

  # Run on custom port
  python tests/template_tcp_server.py --port 8888

  # Bind to specific interface
  python tests/template_tcp_server.py --host 192.168.1.100 --port 9999
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

    args = parser.parse_args()

    server = TemplateTcpServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
