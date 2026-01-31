# Template Quick Reference

This document provides a quick reference for the protocol server templates, which are designed to help you create realistic test targets for the fuzzer.

## 1. The Templates

| File | Purpose |
|------|---------|
| `tests/template_tcp_server.py` | A robust TCP server template that handles message framing. |
| `tests/template_udp_server.py` | A simple UDP server template for datagram-based protocols. |
| `docs/PROTOCOL_SERVER_TEMPLATES.md` | The comprehensive guide with full examples. |

## 2. Quick Start

```bash
# 1. Copy the appropriate template
cp tests/template_tcp_server.py tests/my_tcp_server.py

# 2. Edit the customization points (search for "CUSTOMIZE")
#    - Import your protocol plugin
#    - Implement _calculate_message_size() (for TCP)
#    - Implement _process_message() to define server logic

# 3. Run your new server
python tests/my_tcp_server.py --port 9999
```

## 3. TCP vs. UDP Templates

### TCP Template (`template_tcp_server.py`)
-   **Use for**: Connection-oriented protocols (most common).
-   **Key Method**: `_calculate_message_size()`. **You MUST implement this correctly.** It tells the server how many bytes to read for a complete message. Failure to do this is the #1 cause of test failures.
-   **Complexity**: Higher, due to the need for message framing.

### UDP Template (`template_udp_server.py`)
-   **Use for**: Connectionless protocols.
-   **Key Method**: `_process_message()`. Much simpler as datagrams are self-contained.
-   **Complexity**: Lower.

---

## 4. The #1 TCP Mistake: Deadlock
A fuzzer opens a connection and sends data continuously. A simple `sock.recv(4096)` will either read an incomplete message or block forever, causing a hang. You **must** read the exact message size.

**The templates provide a `read_exactly(sock, num_bytes)` helper for this!**

**How to implement `_calculate_message_size`:**
This function receives an initial chunk of data and must return the *total size of the expected message*.

**Example**: Your protocol is `[Magic: 4B][Length: 4B][Payload: N B]`
```python
def _calculate_message_size(self, buffer: bytes) -> int:
    # We need at least 8 bytes to read the length
    if len(buffer) < 8:
        return -1 # Not enough data yet

    # The length field is at offset 4, is 4 bytes long, big-endian
    payload_len = struct.unpack('>I', buffer[4:8])[0]

    # Total message size is header (8 bytes) + payload
    return 8 + payload_len
```
The server template uses this return value to `read_exactly()` the complete message before calling `_process_message`.

---

## 5. Servers for Orchestrated Sessions

If you are building a test server for a protocol that uses an **Orchestrated Session**, your server must correctly implement the logic for each stage.

-   **Handle `bootstrap` messages**: Your `_process_message` logic must recognize the handshake message from the `bootstrap` stage plugin.
-   **Return Required Data**: If the `bootstrap` stage `exports` a value (like a session token), your server must return a response that contains that value in the expected format.
-   **Handle `fuzz_target` messages**: After the handshake, the server must correctly process the fuzzed messages from the `fuzz_target` stage.
-   **Handle `heartbeat` messages**: If the protocol uses heartbeats, the server should correctly respond to PINGs to keep the connection alive.

**Example Logic in `_process_message`**:
```python
def _process_message(self, fields: dict, addr: tuple) -> bytes:
    command = fields.get("command")

    if command == "HELLO":
        # This is the bootstrap stage
        session_token = self._generate_token()
        self.sessions[addr] = session_token
        return self._build_response({"status": "OK", "token": session_token})

    elif command == "FUZZ_DATA":
        # This is the fuzz_target stage
        client_token = fields.get("session_token")
        if self.sessions.get(addr) != client_token:
            return self._build_response({"status": "ERROR", "message": "Bad Token"})
        # ... process fuzzed data ...
        return self._build_response({"status": "OK"})

    elif command == "PING":
        # This is a heartbeat
        return self._build_response({"status": "PONG"})
```

## 6. Testing Your Server

### Manual Test (TCP)
```bash
# Send raw bytes from your protocol's seeds
echo -ne '\xDE\xAD\xBE\xEF...' | nc localhost 9999 | xxd
```

### With the Fuzzer
1.  **Create a session** pointing to your server (`localhost:9999`).
2.  **Start the session**.
3.  **Check for hangs**. If all tests are hanging, your server is likely deadlocked. Review your `_calculate_message_size()` implementation.
4.  **Check server logs**. The templates have built-in logging. Use the `--verbose` flag to see detailed logs.

---
## Resources
-   **Full Guide**: `docs/PROTOCOL_SERVER_TEMPLATES.md`
-   **Complex Example**: `tests/feature_showcase_server.py` (handles orchestration).
-   **Simple Example**: `tests/simple_tcp_server.py`.
