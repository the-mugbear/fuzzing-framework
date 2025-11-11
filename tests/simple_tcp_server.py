"""
Simple TCP echo server for fuzzing/debugging

The server now echoes exactly what it receives without enforcing protocol
validations so contributors can observe the raw payloads being transmitted.
"""
import socket
import sys
import threading


COLORS = {
    "reset": "\033[0m",
    "blue": "\033[94m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "red": "\033[91m",
    "magenta": "\033[95m",
}

class SimpleTCPServer:
    """Minimal TCP echo utility for inspecting fuzz payloads"""

    def __init__(self, host: str = "0.0.0.0", port: int = 9999):
        self.host = host
        self.port = port
        self.running = False
        self.server_socket = None
        self._color_enabled = sys.stdout.isatty()

    def start(self):
        """Start the server"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True

        self._print_banner()
        self._log("info", f"Listening on {self.host}:{self.port}")

        try:
            while self.running:
                try:
                    client_sock, addr = self.server_socket.accept()
                    self._log("success", f"Connection from {addr[0]}:{addr[1]}")
                    # Handle in thread for concurrent connections
                    thread = threading.Thread(target=self.handle_client, args=(client_sock,))
                    thread.daemon = True
                    thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self._log("error", f"Accept error: {e}")
        except KeyboardInterrupt:
            self._log("info", "Shutting down...")
        finally:
            self.stop()

    def stop(self):
        """Stop the server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()

    def handle_client(self, client_sock: socket.socket):
        """Handle a client connection"""
        try:
            chunk_idx = 1
            while True:
                data = client_sock.recv(4096)
                if not data:
                    if chunk_idx == 1:
                        self._log("debug", "Client closed without sending data")
                    break

                preview = data[:32]
                preview_display = preview.hex()
                if len(data) > len(preview):
                    preview_display += "..."

                self._log(
                    "info",
                    f"Chunk {chunk_idx}: {len(data)} bytes received",
                )
                self._log("debug", f"Payload preview: {preview_display}")

                # echo
                client_sock.sendall(data)
                chunk_idx += 1

            client_sock.close()

        except Exception as e:
            self._log("error", f"Error handling client: {e}")
            try:
                client_sock.close()
            except:
                pass

    def _print_banner(self) -> None:
        border = "=" * 60
        self._log_raw(border, color="blue")
        title = " SimpleTCP Test Server "
        padded_title = title.center(len(border), "=")
        self._log_raw(padded_title, color="magenta")
        self._log_raw(border, color="blue")

    def _log(self, level: str, message: str) -> None:
        level = level.lower()
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


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="SimpleTCP Test Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9999, help="Port to bind to")

    args = parser.parse_args()

    server = SimpleTCPServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
