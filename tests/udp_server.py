"""Simple UDP server for exercising the SimpleUDP protocol plugin."""
from __future__ import annotations

import argparse
import socket
import sys
import threading
from typing import Tuple


COLORS = {
    "reset": "\033[0m",
    "blue": "\033[94m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "red": "\033[91m",
    "magenta": "\033[95m",
}


class SimpleUDPServer:
    """Minimal UDP echo-style server with structured logging."""

    def __init__(self, host: str = "0.0.0.0", port: int = 9999):
        self.host = host
        self.port = port
        self.running = False
        self.socket: socket.socket | None = None
        self._color_enabled = sys.stdout.isatty()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.host, self.port))
        self.running = True
        self._print_banner()
        self._log("info", f"Listening for UDP datagrams on {self.host}:{self.port}")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        try:
            while self.running:
                self._thread.join(timeout=0.5)
        except KeyboardInterrupt:
            self._log("info", "Shutting down...")
        finally:
            self.stop()

    def stop(self) -> None:
        self.running = False
        if self.socket:
            self.socket.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        assert self.socket is not None
        while self.running:
            try:
                data, addr = self.socket.recvfrom(4096)
            except OSError:
                break
            if not data:
                continue
            preview = data[:32].hex()
            if len(data) > 32:
                preview += "..."
            self._log(
                "info",
                f"Datagram from {addr[0]}:{addr[1]} ({len(data)} bytes): {preview}",
            )
            response = self._build_response(data)
            try:
                self.socket.sendto(response, addr)
            except OSError as exc:
                self._log("error", f"Failed to send response: {exc}")

    @staticmethod
    def _build_response(data: bytes) -> bytes:
        if len(data) >= 6 and data.startswith(b"SUDP"):
            # Flip the command byte to indicate server acknowledgement
            prefix = data[:5]
            command = data[5]
            ack_command = (command + 0x80) & 0xFF
            return prefix + bytes([ack_command]) + data[6:]
        return data

    def _print_banner(self) -> None:
        border = "=" * 60
        self._log_raw(border, color="blue")
        title = " SimpleUDP Test Server "
        self._log_raw(title.center(len(border), "="), color="magenta")
        self._log_raw(border, color="blue")

    def _log(self, level: str, message: str) -> None:
        color = {
            "info": "blue",
            "success": "green",
            "warning": "yellow",
            "error": "red",
            "debug": "magenta",
        }.get(level, "reset")
        label = level.upper().ljust(7)
        prefix = self._colorize(f"[{label}]", color)
        print(f"{prefix} {message}")

    def _log_raw(self, message: str, color: str = "reset") -> None:
        print(self._colorize(message, color))

    def _colorize(self, message: str, color: str) -> str:
        if not self._color_enabled or color not in COLORS:
            return message
        return f"{COLORS[color]}{message}{COLORS['reset']}"


def main() -> None:
    parser = argparse.ArgumentParser(description="SimpleUDP Test Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9999, help="Port to bind to")
    args = parser.parse_args()
    server = SimpleUDPServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
