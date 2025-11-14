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
                    client_sock, addr = self.server_socket.accept()
                    self._log("success", f"Connection from {addr[0]}:{addr[1]}")
                    thread = threading.Thread(target=self.handle_client, args=(client_sock,))
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

    def handle_client(self, client_sock: socket.socket) -> None:
        """Receive a single request, craft a protocol-aware response, and close."""
        buffer = b""
        try:
            client_sock.settimeout(5)
            while True:
                chunk = client_sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk

            if not buffer:
                self._log("warning", "Client closed without sending data")
                return

            try:
                fields = self.request_parser.parse(buffer)
            except ValueError as exc:
                self._log("error", f"Failed to parse request: {exc}")
                response = self._build_response(
                    status=0xFF,
                    session_token=0,
                    details=f"Malformed request: {exc}".encode(),
                )
                client_sock.sendall(response)
                return

            response = self._process_message(fields)
            client_sock.sendall(response)

        except socket.timeout:
            self._log("warning", "Client timed out without closing connection")
        except Exception as exc:
            self._log("error", f"Error handling client: {exc}")
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def _process_message(self, fields: Dict[str, object]) -> bytes:
        """Dispatch based on message_type and craft an appropriate response."""
        label, trace_id = self._next_message_label()
        magic = fields.get("magic")
        if magic != b"SHOW":
            return self._build_response(
                status=0xFF,
                session_token=0,
                details=b"Invalid magic header; expected 'SHOW'",
                session_state="BAD_MAGIC",
                trace_id=trace_id,
                label=label,
            )

        msg_value = fields.get("message_type")
        msg_name = self.message_types.get(msg_value, "UNKNOWN")
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
        )
        if isinstance(session_id, int) and session_id in self.sessions:
            self.sessions[session_id]["last_trace_cookie"] = trace_cookie
        return handler(fields, label, trace_id)

    def _handle_handshake(self, fields: Dict[str, object], label: str, trace_id: int) -> bytes:
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
        )

    def _handle_data_stream(self, fields: Dict[str, object], label: str, trace_id: int) -> bytes:
        session_id = fields.get("session_id")
        payload = fields.get("payload") or b""
        meta = fields.get("metadata") or ""

        if not isinstance(session_id, int) or session_id not in self.sessions:
            return self._build_response(
                status=0xFF,
                session_token=0,
                details=b"Unknown session_id. Start with HANDSHAKE_REQUEST.",
                session_state="UNKNOWN_SESSION",
                trace_id=trace_id,
                label=label,
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
        )

    def _handle_heartbeat(self, fields: Dict[str, object], label: str, trace_id: int) -> bytes:
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
        )

    def _handle_terminate(self, fields: Dict[str, object], label: str, trace_id: int) -> bytes:
        session_id = fields.get("session_id")
        if isinstance(session_id, int) and session_id in self.sessions:
            self.sessions.pop(session_id, None)
            details = f"Session 0x{session_id:016X} terminated. Goodbye.".encode()
            return self._build_response(
                status=0x00,
                session_token=0,
                details=details,
                session_state="CLOSED",
                trace_id=trace_id,
                label=label,
            )

        return self._build_response(
            status=0xFF,
            session_token=0,
            details=b"Terminate called without an active session.",
            session_state="ERROR",
            trace_id=trace_id,
            label=label,
        )

    def _handle_unknown_message(self, fields: Dict[str, object], label: str, trace_id: int) -> bytes:
        msg_value = fields.get("message_type")
        details = f"Unsupported message_type {msg_value}. Start with HANDSHAKE.".encode()
        return self._build_response(
            status=0xFF,
            session_token=0,
            details=details,
            session_state="UNKNOWN",
            trace_id=trace_id,
            label=label,
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
    ) -> bytes:
        """Serialize a response message using the plugin's response_model."""
        advice = b"Send HEARTBEAT periodically." if status == 0x00 else b"Retry after handshake."
        trace_value = (trace_id if trace_id is not None else self.message_counter) & 0xFFFFFFFF
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

    def _log(self, level: str, message: str) -> None:
        color = {
            "info": "blue",
            "success": "green",
            "warning": "yellow",
            "error": "red",
            "debug": "magenta",
        }.get(level, "reset")
        prefix = self._colorize(f"[{level.upper():7}]", color)
        print(f"{prefix} {message}")

    def _log_raw(self, message: str, color: str = "reset") -> None:
        print(self._colorize(message, color))


def main() -> None:
    parser = argparse.ArgumentParser(description="Feature Showcase protocol server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9001, help="Port to bind to")
    args = parser.parse_args()

    server = FeatureShowcaseServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
