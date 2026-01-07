"""
Interactive server for the Feature Showcase protocol.

Unlike the generic echo server, this implementation understands
`core/plugins/feature_showcase.py` and crafts meaningful responses so
contributors can observe the response-driven workflow (session tokens,
status codes, etc.).
"""
from __future__ import annotations

import argparse
import secrets
import socket
import sys
import threading
from datetime import datetime
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# Ensure the repository root is on sys.path when running inside containers.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from core.engine.protocol_parser import ProtocolParser
from core.plugins import feature_showcase


class FeatureShowcaseServer:
    """Stateful TCP server tailored for the Feature Showcase protocol."""

    def __init__(self, host: str = "0.0.0.0", port: int = 9001) -> None:
        self.host = host
        self.port = port
        self.running = False
        self.server_socket: Optional[socket.socket] = None
        self._color_enabled = sys.stdout.isatty()

        # The same ProtocolParser used by the core orchestrator is reused here
        # so this server mirrors the exact serialization/parsing logic that the
        # fuzzing engine relies on. Keeping the parser definitions colocated
        # with the plugin means you can copy this server as a template for your
        # own protocols without having to hand-roll struct unpacking code.
        self.request_parser = ProtocolParser(feature_showcase.data_model)
        self.response_parser = ProtocolParser(feature_showcase.response_model)
        self.message_types = self._build_message_type_map()
        # Track active sessions keyed by token
        self.sessions: Dict[int, Dict[str, str]] = {}
        self.message_counter = 0

    def _build_message_type_map(self) -> Dict[int, str]:
        """Invert the `values` mapping on the message_type block."""
        for block in feature_showcase.data_model.get("blocks", []):
            if block.get("name") == "message_type" and "values" in block:
                return {value: name for value, name in block["values"].items()}
        return {}

    def start(self) -> None:
        """Start listening for connections."""
        # Using a blocking TCP socket keeps the implementation approachable; if
        # you are adapting this to your own plugin you can lift this boilerplate
        # and only change the handler logic.
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True

        self._print_banner()
        self._log("info", f"Feature Showcase server on {self.host}:{self.port}")

        try:
            while self.running:
                try:
                    # Accept each client and spawn a thread—this avoids mixing
                    # protocol logic with asyncio and keeps the example easy to
                    # follow even for new contributors.
                    client_sock, addr = self.server_socket.accept()
                    self._log("success", f"Connection from {addr[0]}:{addr[1]}", client_addr=addr)
                    thread = threading.Thread(target=self.handle_client, args=(client_sock, addr))
                    thread.daemon = True
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
        """Stop the server."""
        self.running = False
        if self.server_socket:
            self.server_socket.close()

    def handle_client(self, client_sock: socket.socket, addr: tuple) -> None:
        """Receive a single request, craft a protocol-aware response, and close.

        IMPORTANT FOR PROTOCOL IMPLEMENTERS:
        =====================================
        This method demonstrates the CORRECT way to receive messages from the fuzzer.

        THE PROBLEM WITH NAIVE APPROACHES:
        -----------------------------------
        A common mistake is to use a blocking receive loop like:

            while True:
                chunk = sock.recv(4096)
                if not chunk:  # Wait for client to close
                    break
                buffer += chunk

        This creates a DEADLOCK with the fuzzer because:
        1. Fuzzer sends data and KEEPS CONNECTION OPEN waiting for response
        2. Server waits for connection close before processing
        3. Both sides wait forever (until timeout)

        THE SOLUTION:
        -------------
        Read the message intelligently based on protocol structure:
        1. Read a fixed-size header that contains length fields
        2. Parse length fields to determine total message size
        3. Read remaining bytes until complete message received
        4. Process and respond IMMEDIATELY (don't wait for connection close)

        For protocols with simple framing (like newline-terminated), you can read
        until you see the delimiter. For length-prefixed binary protocols (like
        this one), calculate the exact message size from length fields.
        """
        self._log_raw("") # Newline before session starts
        self._log("success", f"Session started from {addr[0]}:{addr[1]}", client_addr=addr)
        buffer = b""
        session_id_for_logging = None # To capture session ID if it becomes available

        try:
            # Set a reasonable timeout for receiving data. This timeout applies
            # to individual recv() calls, not the entire message. Adjust based
            # on your network conditions and testing needs.
            #
            # For local testing: 0.5-1.0 seconds is plenty
            # For network testing: 2-5 seconds may be needed
            # For fuzzing: Keep it short (0.5-1s) to catch hangs quickly
            client_sock.settimeout(1.0)

            # ================================================================
            # STEP 1: Read the minimum fixed header
            # ================================================================
            # For this protocol, we need at least the initial fields to
            # determine message length. The structure is:
            #   Offset  Size  Field
            #   ------  ----  -----
            #   0       4     magic
            #   4       1     protocol_version
            #   5       1     header_len
            #   6       2     header_checksum
            #   8       1     message_type
            #   9       2     flags
            #   11      8     session_id
            #   19      4     payload_len <- KEY: First length field we need!
            #
            # So we need to read at least 19+4 = 23 bytes to get payload_len.
            # After that, we'll need to read more to get metadata_len (which
            # comes after the variable-length payload).
            #
            # NOTE: For your own protocol, adjust this to include all fixed
            # fields up to and including the FIRST length field.
            MIN_HEADER_SIZE = 23  # Enough to include payload_len field

            # Read initial header. We use a loop here because recv() might
            # return less than requested (especially over networks).
            while len(buffer) < MIN_HEADER_SIZE:
                chunk = client_sock.recv(MIN_HEADER_SIZE - len(buffer))
                if not chunk:
                    # Client closed connection before sending complete header
                    self._log("warning", f"Client closed connection after sending only {len(buffer)} bytes (expected at least {MIN_HEADER_SIZE})", client_addr=addr)
                    self._log_raw("")
                    return
                buffer += chunk

            # ================================================================
            # STEP 2: Parse length fields from the header
            # ================================================================
            # Extract the variable-length field sizes from the header we just read.
            # These tell us how much MORE data to read after the fixed fields.
            #
            # For Feature Showcase protocol:
            #   - Bytes 19-23 (4 bytes): payload_len (uint32, big-endian)
            #   - Bytes after payload: metadata_len (uint16, big-endian)
            #
            # We need to be careful about endianness! Check your protocol spec.
            # The feature_showcase protocol uses big-endian for payload_len and
            # metadata_len (network byte order).
            import struct

            # payload_len is at offset 19 (after magic[4] + version[1] + header_len[1] +
            # checksum[2] + msg_type[1] + flags[2] + session_id[8] = 19)
            payload_len = struct.unpack('>I', buffer[19:23])[0]  # '>I' = big-endian uint32

            # ================================================================
            # STEP 3: Calculate total message size
            # ================================================================
            # Now we know the payload size, but we still need to get metadata_len
            # which comes AFTER the payload. The complete message structure is:
            #
            # Offset  Size            Field
            # ------  ----            -----
            # 0-22    23              Fixed header (including payload_len)
            # 23      payload_len     Payload data (variable)
            # 23+N    2               metadata_len field
            # 23+N+2  metadata_len    Metadata data (variable)
            # ...     9               Trailing fixed fields (see below)
            #
            # STRATEGY: Read in stages because metadata_len comes after payload
            # 1. Read up to and including metadata_len field
            # 2. Parse metadata_len value
            # 3. Calculate final total and read remaining bytes

            # First, read through the payload and metadata_len field
            bytes_needed_for_metadata_len = 23 + payload_len + 2  # header + payload + metadata_len field

            while len(buffer) < bytes_needed_for_metadata_len:
                bytes_to_read = bytes_needed_for_metadata_len - len(buffer)
                chunk = client_sock.recv(min(bytes_to_read, 4096))
                if not chunk:
                    self._log("warning", f"Client closed connection while reading payload (got {len(buffer)}/{bytes_needed_for_metadata_len} bytes)", client_addr=addr)
                    self._log_raw("")
                    return
                buffer += chunk

            # Now we can parse metadata_len (comes right after payload)
            metadata_len_offset = 23 + payload_len
            metadata_len = struct.unpack('>H', buffer[metadata_len_offset:metadata_len_offset+2])[0]  # '>H' = big-endian uint16

            # Calculate final total message size including trailing fields
            # Trailing fields after metadata:
            #   - telemetry_counter: uint16 (2 bytes)
            #   - opcode_bias: uint8 (1 byte)
            #   - trace_cookie: uint32 (4 bytes)
            #   - footer_marker: 2 bytes
            #   Total: 2+1+4+2 = 9 bytes
            TRAILING_FIELDS_SIZE = 9

            # Complete message size calculation:
            # header(23) + payload(N) + metadata_len_field(2) + metadata(M) + trailing(9)
            total_message_size = 23 + payload_len + 2 + metadata_len + TRAILING_FIELDS_SIZE

            # ================================================================
            # STEP 4: Read remaining message bytes
            # ================================================================
            # Continue reading until we have the complete message
            while len(buffer) < total_message_size:
                bytes_to_read = total_message_size - len(buffer)
                chunk = client_sock.recv(min(bytes_to_read, 4096))
                if not chunk:
                    self._log("warning", f"Client closed connection while reading message (got {len(buffer)}/{total_message_size} bytes)", client_addr=addr)
                    self._log_raw("")
                    return
                buffer += chunk

            # ================================================================
            # SUCCESS: We have a complete message!
            # ================================================================
            # At this point, buffer contains exactly one complete protocol message.
            # We can now parse and process it WITHOUT waiting for the client
            # to close the connection.
            #
            # IMPORTANT: Some protocols allow multiple messages per connection.
            # If your protocol supports that, you would:
            # 1. Process this message
            # 2. Remove processed bytes from buffer: buffer = buffer[total_message_size:]
            # 3. Loop back to read the next message
            # 4. Exit loop when client closes or sends a termination message
            #
            # For this server, we process one message and close (simpler for fuzzing).

            if not buffer:
                self._log("info", "Session ended: client closed without sending data", client_addr=addr)
                self._log_raw("") # Newline after session ends
                return

            try:
                # Parse the inbound message using the same declarative data
                # model from the plugin. If you add or remove fields in the
                # plugin, the parser automatically stays in sync.
                fields = self.request_parser.parse(buffer)
                session_id_for_logging = fields.get("session_id")
            except ValueError as exc:
                self._log("error", f"Failed to parse request: {exc}", client_addr=addr)
                context = (
                    "Malformed request while parsing Feature Showcase message. "
                    f"Parser raised: {exc}. Ensure fields match the plugin layout."
                )
                response = self._build_response(
                    status=0xFF,
                    session_token=0,
                    details=context.encode(),
                    session_state="PARSE_ERROR",
                    client_addr=addr
                )
                client_sock.sendall(response)
                self._log("warning", f"Session ended with parsing error: {exc}", client_addr=addr)
                self._log_raw("") # Newline after session ends
                return

            response = self._process_message(fields, addr)
            client_sock.sendall(response)
            self._log("info", f"Session ended gracefully for session ID: {session_id_for_logging or 'N/A'}", client_addr=addr)
            self._log_raw("") # Newline after session ends

        except socket.timeout:
            self._log("warning", "Session ended: client timed out without closing connection", client_addr=addr)
            self._log_raw("") # Newline after session ends
        except Exception as exc:
            self._log("error", f"Session ended with unexpected error: {exc}", client_addr=addr)
            self._log_raw("") # Newline after session ends
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def _process_message(self, fields: Dict[str, object], client_addr: tuple) -> bytes:
        """Dispatch based on message_type and craft an appropriate response."""
        label, trace_id = self._next_message_label()
        magic = fields.get("magic")
        if magic != b"SHOW":
            details = (
                b"Magic header mismatch: expected 'SHOW', "
                + repr(magic or b"<missing>").encode()
                + b" received. Update your plugin seeds or target server."
            )
            return self._build_response(
                status=0xFF,
                session_token=0,
                details=details,
                session_state="BAD_MAGIC",
                trace_id=trace_id,
                label=label,
                client_addr=client_addr
            )

        msg_value = fields.get("message_type")
        msg_name = self.message_types.get(msg_value, "UNKNOWN")
        # Map message type to handler functions so contributors can see how to
        # wire state transitions to concrete server behavior.
        handler = {
            "HANDSHAKE_REQUEST": self._handle_handshake,
            "DATA_STREAM": self._handle_data_stream,
            "DATA_ACK": self._handle_data_stream,
            "HEARTBEAT": self._handle_heartbeat,
            "TERMINATE": self._handle_terminate,
        }.get(msg_name, self._handle_unknown_message)

        session_id = fields.get("session_id")
        session_state = self._describe_session_state(session_id)
        trace_cookie = fields.get("trace_cookie") or 0
        self._log(
            "info",
            f"{label} Received {msg_name} ({msg_value}) · session={session_state} · trace_cookie=0x{trace_cookie:08X}",
            client_addr=client_addr
        )
        if isinstance(session_id, int) and session_id in self.sessions:
            self.sessions[session_id]["last_trace_cookie"] = trace_cookie
        return handler(fields, label, trace_id, client_addr)

    def _handle_handshake(self, fields: Dict[str, object], label: str, trace_id: int, client_addr: tuple) -> bytes:
        session_token = secrets.randbits(64)
        self.sessions[session_token] = {"state": "HANDSHAKE"}
        details = (
            f"Handshake accepted. Session token 0x{session_token:016X}. "
            "Follow up with DATA_STREAM to push payloads."
        ).encode()
        return self._build_response(
            status=0x00,
            session_token=session_token,
            details=details,
            session_state="HANDSHAKE",
            trace_id=trace_id,
            label=label,
            client_addr=client_addr
        )

    def _handle_data_stream(self, fields: Dict[str, object], label: str, trace_id: int, client_addr: tuple) -> bytes:
        session_id = fields.get("session_id")
        payload = fields.get("payload") or b""
        meta = fields.get("metadata") or ""

        if not isinstance(session_id, int) or session_id not in self.sessions:
            detail = (
                b"DATA_STREAM received without a valid session_id. "
                b"Begin with HANDSHAKE_REQUEST to establish a session before sending data."
            )
            return self._build_response(
                status=0xFF,
                session_token=0,
                details=detail,
                session_state="UNKNOWN_SESSION",
                trace_id=trace_id,
                label=label,
                client_addr=client_addr
            )

        payload_preview = payload[:16] if isinstance(payload, (bytes, bytearray)) else b""
        self.sessions[session_id]["state"] = "ESTABLISHED"
        details = (
            f"Accepted DATA_STREAM ({len(payload)} bytes). "
            f"Preview: {payload_preview.hex()} "
            f"Metadata: {meta!r}"
        ).encode()

        return self._build_response(
            status=0x00,
            session_token=session_id,
            details=details,
            session_state="ESTABLISHED",
            trace_id=trace_id,
            label=label,
            client_addr=client_addr
        )

    def _handle_heartbeat(self, fields: Dict[str, object], label: str, trace_id: int, client_addr: tuple) -> bytes:
        session_id = fields.get("session_id")
        details = (
            f"Heartbeat acknowledged for session 0x{session_id:016X}"
            if isinstance(session_id, int)
            else "Heartbeat acknowledged."
        ).encode()
        return self._build_response(
            status=0x00,
            session_token=session_id if isinstance(session_id, int) else 0,
            details=details,
            session_state="HEARTBEAT",
            trace_id=trace_id,
            label=label,
            client_addr=client_addr
        )

    def _handle_terminate(self, fields: Dict[str, object], label: str, trace_id: int, client_addr: tuple) -> bytes:
        session_id = fields.get("session_id")
        if isinstance(session_id, int) and session_id in self.sessions:
            self.sessions.pop(session_id, None)
            details = (
                f"Session 0x{session_id:016X} terminated per TERMINATE request. "
                "All subsequent traffic must start with HANDSHAKE_REQUEST."
            ).encode()
            return self._build_response(
                status=0x00,
                session_token=0,
                details=details,
                session_state="CLOSED",
                trace_id=trace_id,
                label=label,
                client_addr=client_addr
            )

        return self._build_response(
            status=0xFF,
            session_token=0,
            details=b"Terminate called without an active session.",
            session_state="ERROR",
            trace_id=trace_id,
            label=label,
            client_addr=client_addr
        )

    def _handle_unknown_message(self, fields: Dict[str, object], label: str, trace_id: int, client_addr: tuple) -> bytes:
        msg_value = fields.get("message_type")
        details = (
            f"Unsupported message_type {msg_value}. "
            "Ensure seeds use HANDSHAKE_REQUEST → DATA_STREAM → HEARTBEAT → TERMINATE."
        ).encode()
        return self._build_response(
            status=0xFF,
            session_token=0,
            details=details,
            session_state="UNKNOWN",
            trace_id=trace_id,
            label=label,
            client_addr=client_addr
        )

    def _describe_session_state(self, session_id: Optional[int]) -> str:
        if isinstance(session_id, int) and session_id in self.sessions:
            return self.sessions[session_id].get("state", "INIT")
        return "NEW"

    def _next_message_label(self) -> tuple[str, int]:
        self.message_counter += 1
        return f"[msg#{self.message_counter:04d}]", self.message_counter

    def _build_response(
        self,
        status: int,
        session_token: int,
        details: bytes,
        session_state: str = "N/A",
        trace_id: Optional[int] = None,
        label: Optional[str] = None,
        client_addr: Optional[tuple] = None,
    ) -> bytes:
        """Serialize a response message using the plugin's response_model."""
        advice = b"Send HEARTBEAT periodically." if status == 0x00 else b"Retry after handshake."
        trace_value = (trace_id if trace_id is not None else self.message_counter) & 0xFFFFFFFF
        # Build the outbound response by filling a plain dict and letting the
        # ProtocolParser handle serialization. This demonstrates how plugins
        # can be used bi-directionally (requests + responses) without custom
        # struct packing.
        fields = {
            "magic": b"SHOW",
            "protocol_version": 1,
            "status": status,
            "session_token": session_token,
            "server_nonce": secrets.randbits(32),
            "details": details,
            "trace_id": trace_value,
            "advice": f"{session_state}: {advice.decode()}",
        }
        response = self.response_parser.serialize(fields)
        self._log(
            "debug",
            f"{label or '[response]'} Responding with status=0x{status:02X}, session=0x{session_token:016X}, trace_id=0x{trace_value:08X}",
            client_addr=client_addr
        )
        return response

    # --- Pretty logging helpers -------------------------------------------------
    def _print_banner(self) -> None:
        border = "=" * 70
        self._log_raw(border, color="blue")
        self._log_raw(" Feature Showcase reference server ".center(70), color="magenta")
        self._log_raw(border, color="blue")

    def _colorize(self, message: str, color: str) -> str:
        COLORS = {
            "reset": "\033[0m",
            "blue": "\033[94m",
            "green": "\033[92m",
            "yellow": "\033[93m",
            "red": "\033[91m",
            "magenta": "\033[95m",
        }
        if not self._color_enabled or color not in COLORS:
            return message
        return f"{COLORS[color]}{message}{COLORS['reset']}"

    def _log(self, level: str, message: str, client_addr: Optional[tuple] = None) -> None:
        color = {
            "info": "blue",
            "success": "green",
            "warning": "yellow",
            "error": "red",
            "debug": "magenta",
        }.get(level, "reset")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if client_addr:
            prefix = self._colorize(f"[{timestamp}][{level.upper():7} {client_addr[0]}:{client_addr[1]}]", color)
        else:
            prefix = self._colorize(f"[{timestamp}][{level.upper():7}]", color)
        print(f"{prefix} {message}")

    def _log_raw(self, message: str, color: str = "reset", client_addr: Optional[tuple] = None) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if client_addr:
            prefix = self._colorize(f"[{timestamp}]", color)
        else:
            prefix = self._colorize(f"[{timestamp}]", color)
        print(f"{prefix} {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Feature Showcase protocol server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9001, help="Port to bind to")
    args = parser.parse_args()

    server = FeatureShowcaseServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
