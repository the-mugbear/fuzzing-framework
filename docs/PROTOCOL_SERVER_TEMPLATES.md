# Protocol Server Templates Guide

This guide explains how to use the TCP and UDP server templates to implement custom protocol servers for fuzzing verification and validation testing.

## 1. Overview

The protocol server templates provide fully-documented starting points for implementing servers that work correctly with the fuzzer. A well-crafted test server is essential for verifying your protocol plugin and for testing stateful logic.

-   **TCP Template**: `tests/template_tcp_server.py`
-   **UDP Template**: `tests/template_udp_server.py`

## 2. When to Use Which Template

-   **TCP**: Use for connection-oriented, reliable protocols (HTTP, stateful binary protocols). This is the most common choice.
-   **UDP**: Use for connectionless, low-latency protocols (DNS, NTP, game traffic).

---

## 3. TCP Template Guide

The most critical part of a TCP server is **message framing**. Because TCP is a stream, you are responsible for identifying message boundaries. Failure to do this correctly is the #1 cause of fuzzing sessions hanging.

### The Deadlock Problem (And How to Avoid It)
A simple `sock.recv(4096)` will block until 4096 bytes are received or the connection is closed. The fuzzer keeps the connection open, leading to a deadlock.

**✅ The Solution: Read Exactly What You Need**
The template provides a `read_exactly(sock, num_bytes)` helper function. To use it, you must tell the server how to calculate the total size of an incoming message.

#### **CUSTOMIZATION POINT: `_calculate_message_size()`**
You **MUST** implement this method. It receives an initial buffer of data and must return the total expected size of the complete message.

**Example**: Your protocol is `[Magic: 4B][Length: 4B][Payload: N B]`.
```python
# In your server class:
def _calculate_message_size(self, buffer: bytes) -> int:
    # We need at least 8 bytes to read the length field.
    if len(buffer) < 8:
        return -1 # Tell the template we need more data.

    # The length field is at offset 4, is 4 bytes long, big-endian.
    # It specifies the length of the PAYLOAD.
    payload_len = struct.unpack('>I', buffer[4:8])[0]

    # The total message size is the header (8 bytes) + the payload.
    return 8 + payload_len
```
The template's main loop uses this logic to piece together the full message from the stream before passing it to your processing logic.

### Other Customization Points

-   **`__init__()`**: Import your protocol plugin and initialize the `ProtocolParser`.
-   **`_process_message()`**: The core of your server's logic. It receives a dictionary of parsed fields from the request and must return the raw bytes of the response.
-   **`_build_response()`**: A helper to serialize a dictionary of response fields into bytes using your response model.

---

## 4. UDP Template Guide

The UDP template is simpler because datagrams are self-contained messages.

-   **`MAX_DATAGRAM_SIZE`**: Set this to a reasonable value for your protocol to prevent IP fragmentation.
-   **`_process_message()`**: Your core logic. Receives parsed fields and the client address, returns response bytes.

---

## 5. Implementing Servers for Orchestrated Sessions

When fuzzing a protocol with an **Orchestrated Session**, your test server must act as a realistic counterpart, correctly handling each stage of the interaction.

### Server Logic for Orchestration
Your server's `_process_message` function needs to behave like a state machine, responding differently based on the message it receives.

-   **Handle `bootstrap` messages**: It must recognize the handshake message from the `bootstrap` stage plugin.
-   **Return `export` data**: If the `bootstrap` stage `exports` a value (like a session token), the server's response *must* contain that value in the expected format.
-   **Handle `fuzz_target` messages**: After the handshake, the server must correctly validate and process the fuzzed messages, which will contain data injected via `from_context`.
-   **Handle `heartbeat` messages**: The server should respond correctly to PINGs to keep the connection alive.

### Example Orchestrated Server Logic

Let's imagine a protocol that requires a `HELLO` handshake to get a token, which is then used in subsequent `FUZZ` commands.

```python
# In your server's _process_message method:

def _process_message(self, fields: dict, addr: tuple) -> bytes:
    command = fields.get("command_name") # Assuming a field named 'command_name'

    # Stage 1: Bootstrap / Handshake
    if command == "HELLO":
        self._log("info", f"Received HELLO from {addr}. Starting session.")
        session_token = self._generate_new_token()
        self.sessions[addr] = session_token # Store the token server-side

        # Return a response that the bootstrap plugin can parse and export from.
        # The bootstrap plugin will have an `exports` rule to get "token_value".
        return self._build_response({
            "status": "OK",
            "token_value": session_token
        })

    # Stage 2: Fuzz Target
    elif command == "FUZZ":
        client_token = fields.get("session_token") # This field was injected by the fuzzer via from_context

        # Validate the token from the fuzzer against our stored token
        if self.sessions.get(addr) != client_token:
            self._log("warn", f"Bad token from {addr}. Got {client_token}, expected {self.sessions.get(addr)}")
            return self._build_response({"status": "ERROR", "message": "Invalid Session Token"})

        # If token is valid, process the fuzzed data
        fuzzed_data = fields.get("fuzzed_payload")
        self._log("info", f"Processing fuzzed data from {addr}: {fuzzed_data!r}")
        # ... your logic here ...
        return self._build_response({"status": "OK"})

    # Stage 3: Heartbeat
    elif command == "PING":
        return self._build_response({"status": "PONG"})

    else:
        self._log("warn", f"Unknown command: {command}")
        return self._build_response({"status": "ERROR", "message": "Unknown Command"})

```
This example demonstrates how the server maintains state (`self.sessions`) and responds differently depending on the stage of the orchestrated session.

---

## 6. Troubleshooting

-   **All tests hang (TCP)**: Your `_calculate_message_size()` is almost certainly wrong. It's either returning `-1` forever or an incorrect size, causing a deadlock. Add verbose logging to see what it's calculating.
-   **Parse errors**: The `data_model` in your protocol plugin doesn't match the bytes the server is receiving. Check field orders, sizes, and endianness.
-   **Orchestration fails at bootstrap**: Your server is not returning the response that the `bootstrap` plugin expects. Manually send the handshake message (`HELLO` in our example) and verify the server's response contains the data needed for `exports`.

---
## See Also
-   **Quick Reference**: `docs/TEMPLATE_QUICK_REFERENCE.md`
-   **Complex Example**: `tests/feature_showcase_server.py` (handles orchestration).
-   **Simple Example**: `tests/simple_tcp_server.py`.