"""
Simple TCP test server for fuzzing

Implements a basic protocol with intentional vulnerabilities for testing:
- Buffer overflow on large payloads
- Crash on specific magic values
- Memory leak on repeated connections
"""
import socket
import struct
import sys
import threading


class SimpleTCPServer:
    """
    Test server implementing SimpleTCP protocol

    Protocol format:
    - 4 bytes: Magic "STCP"
    - 4 bytes: Length (big-endian uint32)
    - 1 byte: Command (0x01=AUTH, 0x02=DATA, 0x03=QUIT)
    - N bytes: Payload
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9999):
        self.host = host
        self.port = port
        self.running = False
        self.server_socket = None

    def start(self):
        """Start the server"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True

        print(f"[*] SimpleTCP Server listening on {self.host}:{self.port}")

        try:
            while self.running:
                try:
                    client_sock, addr = self.server_socket.accept()
                    print(f"[+] Connection from {addr}")
                    # Handle in thread for concurrent connections
                    thread = threading.Thread(target=self.handle_client, args=(client_sock,))
                    thread.daemon = True
                    thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"[-] Accept error: {e}")
        except KeyboardInterrupt:
            print("\n[*] Shutting down...")
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
            # Receive data
            data = client_sock.recv(4096)
            if len(data) < 9:
                client_sock.close()
                return

            # Parse protocol
            magic = data[:4]
            if magic != b"STCP":
                print(f"[-] Invalid magic: {magic}")
                client_sock.sendall(b"STCP\x00\x00\x00\x01\xFFERROR")
                client_sock.close()
                return

            length = struct.unpack(">I", data[4:8])[0]
            command = data[8]
            payload = data[9 : 9 + length] if len(data) > 9 else b""

            print(f"[+] Command: {command:#x}, Length: {length}, Payload: {len(payload)} bytes")

            # Process command
            if command == 0x01:  # AUTH
                response = self.handle_auth(payload)
            elif command == 0x02:  # DATA
                response = self.handle_data(payload)
            elif command == 0x03:  # QUIT
                response = b"STCP\x00\x00\x00\x02\x03OK"
                client_sock.sendall(response)
                client_sock.close()
                return
            else:
                response = b"STCP\x00\x00\x00\x01\xFFERROR"

            client_sock.sendall(response)
            client_sock.close()

        except Exception as e:
            print(f"[-] Error handling client: {e}")
            try:
                client_sock.close()
            except:
                pass

    def handle_auth(self, payload: bytes) -> bytes:
        """Handle AUTH command"""
        # Intentional vulnerability: buffer overflow on large payload
        if len(payload) > 1024:
            print("[!] VULNERABILITY: Buffer overflow detected!")
            # Simulate crash (would be real overflow in C/C++)
            raise Exception("Buffer overflow")

        if payload == b"CRASH":
            # Intentional crash trigger
            print("[!] VULNERABILITY: Crash trigger activated!")
            raise Exception("Intentional crash")

        # Normal response
        return b"STCP\x00\x00\x00\x05\x01AUTH_OK"

    def handle_data(self, payload: bytes) -> bytes:
        """Handle DATA command"""
        # Intentional vulnerability: specific byte pattern causes crash
        if b"\xde\xad\xbe\xef" in payload:
            print("[!] VULNERABILITY: Magic bytes detected!")
            raise Exception("Magic bytes crash")

        # Normal response: echo back length
        response_payload = f"DATA_OK:{len(payload)}".encode()
        response = b"STCP" + struct.pack(">I", len(response_payload)) + b"\x02" + response_payload
        return response


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
