"""
Reference target for the FunctionalityTest protocol plugin.

Usage:
    python -m tests.functionality_server --host 0.0.0.0 --port 9000

What to watch for in logs:
- "connection from ..." appears when a client opens a socket; the fuzzer opens a fresh connection per test in many modes.
- "client closed ..." is expected when the fuzzer tears down the socket (e.g., after a CLOSE opcode or after reading a response).
- If you see parse errors or "bad length"/"bad magic", your payloads are malformed; otherwise brief connect/close cycles are normal.
"""
import argparse
import asyncio
import logging
from typing import Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("functionality_server")

MAGIC = b"FTST"


def parse_message(data: bytes) -> Tuple[int, int, bytes]:
    if len(data) < 9:
        raise ValueError("message too short")
    if data[:4] != MAGIC:
        raise ValueError("bad magic")
    seq = int.from_bytes(data[4:6], "big")
    opcode = data[6]
    length = int.from_bytes(data[7:9], "big")
    payload = data[9 : 9 + length]
    if length != len(payload):
        raise ValueError("bad length")
    return seq, opcode, payload


def build_message(seq: int, opcode: int, payload: bytes) -> bytes:
    length = len(payload)
    return MAGIC + seq.to_bytes(2, "big") + bytes([opcode]) + length.to_bytes(2, "big") + payload


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    logger.info("connection from %s", peer)
    try:
        while True:
            header = await reader.readexactly(9)
            payload_len = int.from_bytes(header[7:9], "big")
            payload = await reader.readexactly(payload_len)
            seq, opcode, payload = parse_message(header + payload)

            if opcode == 0x01:  # PING
                resp = build_message(seq, 0x81, b"PONG")
            elif opcode == 0x02:  # ECHO
                resp = build_message(seq, 0x82, payload or b"ECHO")
            elif opcode == 0x03:  # FAIL
                resp = build_message(seq, 0xFF, b"FAIL")
            elif opcode == 0x04:  # CLOSE
                resp = build_message(seq, 0x04, b"BYE")
                writer.write(resp)
                await writer.drain()
                break
            else:
                resp = build_message(seq, 0xFF, b"UNKNOWN")

            writer.write(resp)
            await writer.drain()
    except asyncio.IncompleteReadError:
        logger.info("client closed %s", peer)
    except Exception as exc:  # pragma: no cover - best effort logging
        logger.error("connection error %s: %s", peer, exc)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main(host: str, port: int):
    server = await asyncio.start_server(handle_connection, host, port)
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logger.info("FunctionalityTest server listening on %s", sockets)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Functionality Test Protocol server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))
