# Protocol Server Templates Guide

This guide explains how to use the TCP and UDP server templates to implement custom protocol servers for fuzzing verification and validation testing.

## Table of Contents

1. [Overview](#overview)
2. [When to Use Which Template](#when-to-use-which-template)
3. [Quick Start](#quick-start)
4. [TCP Template Guide](#tcp-template-guide)
5. [UDP Template Guide](#udp-template-guide)
6. [Common Patterns](#common-patterns)
7. [Troubleshooting](#troubleshooting)

---

## Overview

The protocol server templates provide fully-documented starting points for implementing servers that work correctly with the fuzzer. They include:

- **TCP Template** (`tests/template_tcp_server.py`): For connection-oriented, stream-based protocols
- **UDP Template** (`tests/template_udp_server.py`): For connectionless, datagram-based protocols

Both templates demonstrate:
- ✅ Correct message framing (avoiding deadlocks)
- ✅ Protocol parser integration
- ✅ Response crafting
- ✅ Error handling
- ✅ Extensive inline documentation

---

## When to Use Which Template

### Use the **TCP Template** when:
- Your protocol requires **reliable, ordered delivery**
- You need **connection state** (sessions, handshakes)
- Your protocol uses **streaming data** (no natural message boundaries)
- Examples: HTTP, FTP, SSH, TLS, custom binary protocols

### Use the **UDP Template** when:
- Your protocol can tolerate **packet loss**
- You need **low latency** over reliability
- Messages are **self-contained** (no fragmentation needed)
- You need **multicast** or **broadcast** capability
- Examples: DNS, DHCP, NTP, SNMP, real-time gaming protocols

### Quick Comparison

| Feature | TCP | UDP |
|---------|-----|-----|
| Connection | Stateful | Stateless |
| Reliability | Guaranteed delivery | Best effort |
| Ordering | In-order delivery | May arrive out of order |
| Overhead | Higher (handshake, acks) | Lower (no connection) |
| Message Boundaries | Stream (need framing) | Datagram (natural boundaries) |
| Complexity | More complex | Simpler |
| Use Case | Reliability critical | Latency critical |

---

## Quick Start

### 1. Choose Your Template

```bash
# Copy the appropriate template
cp tests/template_tcp_server.py tests/my_protocol_server.py
# OR
cp tests/template_udp_server.py tests/my_protocol_server.py
```

### 2. Create Your Protocol Plugin

First, create your protocol definition in `core/plugins/`:

```python
# core/plugins/my_protocol.py

__version__ = "1.0.0"

data_model = {
    "name": "MyProtocol",
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"MYPK"},
        {"name": "length", "type": "uint16", "endian": "big"},
        {"name": "payload", "type": "bytes", "max_size": 1024}
    ]
}

# Optional: Separate response format
response_model = {
    "name": "MyProtocolResponse",
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"RESP"},
        {"name": "status", "type": "uint8"},
        {"name": "data", "type": "bytes", "max_size": 512}
    ]
}
```

### 3. Customize the Template

Open your copied server file and follow the `CUSTOMIZATION POINT` markers:

```python
# CUSTOMIZATION POINT 1: Import your protocol
from core.plugins import my_protocol

# CUSTOMIZATION POINT 2: Initialize parsers
self.request_parser = ProtocolParser(my_protocol.data_model)
self.response_parser = ProtocolParser(my_protocol.response_model)

# Continue through all customization points...
```

### 4. Run Your Server

```bash
# Test locally
python tests/my_protocol_server.py --port 9999

# In Docker
# Update docker-compose.yml CMD for the target service
# Then: docker-compose up -d target
```

### 5. Test with the Fuzzer

```bash
# Create a fuzzing session
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "protocol": "my_protocol",
    "target_host": "localhost",  # or "target" in Docker
    "target_port": 9999,
    "timeout_per_test_ms": 2000
  }'
```

---

## TCP Template Guide

### Understanding TCP Message Framing

The **critical** part of TCP server implementation is message framing. TCP is a **stream protocol** with no natural message boundaries, so you must implement framing logic to know where messages start and end.

#### The Deadlock Problem

**❌ DO NOT DO THIS:**
```python
# WRONG - Creates deadlock with fuzzer!
while True:
    chunk = sock.recv(4096)
    if not chunk:  # Waits for client to close
        break
    buffer += chunk
```

**Why this fails:**
1. Fuzzer sends data and **keeps connection open** waiting for response
2. Server waits for connection close before processing
3. Both sides wait forever (until timeout)

#### The Correct Approach

**✅ DO THIS:**
```python
# CORRECT - Read based on protocol structure
# Step 1: Read fixed header with length field
header = read_exactly(sock, HEADER_SIZE)

# Step 2: Parse length from header
msg_length = struct.unpack('>I', header[OFFSET:OFFSET+4])[0]

# Step 3: Read exact message bytes
remaining = read_exactly(sock, msg_length)

# Step 4: Process and respond immediately
response = process_message(header + remaining)
sock.sendall(response)
```

### TCP Template Customization Points

#### 1. **Message Size Calculation** (Most Important!)

The template provides `_calculate_message_size()` which you **must customize** for your protocol's framing:

**For simple length-prefixed protocols:**
```python
def _calculate_message_size(self, initial_buffer: bytes, client_sock: socket.socket) -> int:
    # If your protocol has a simple length field:
    # Offset 4-7: uint32 big-endian total message length
    total_length = struct.unpack('>I', initial_buffer[4:8])[0]
    return total_length
```

**For protocols with multiple variable sections:**
```python
def _calculate_message_size(self, initial_buffer: bytes, client_sock: socket.socket) -> int:
    # Header: 20 bytes (includes header_len and payload_len)
    header_len = struct.unpack('>H', initial_buffer[10:12])[0]
    payload_len = struct.unpack('>I', initial_buffer[16:20])[0]

    # Total: fixed_prefix + header + payload + fixed_suffix
    return 20 + header_len + payload_len + 8
```

**For delimiter-based protocols (like HTTP):**
```python
def _receive_complete_message(self, client_sock: socket.socket, addr: tuple) -> bytes:
    # Read until delimiter
    buffer = b""
    delimiter = b"\r\n\r\n"  # HTTP header end

    while delimiter not in buffer:
        chunk = client_sock.recv(4096)
        if not chunk:
            return buffer
        buffer += chunk

    return buffer
```

#### 2. **Message Processing Logic**

Implement your protocol's state machine and business logic:

```python
def _process_message(self, fields: Dict[str, any], addr: tuple) -> bytes:
    # Extract fields
    cmd = fields.get("command")
    payload = fields.get("payload", b"")

    # Dispatch to handlers
    if cmd == 0x01:  # CONNECT
        return self._handle_connect(fields)
    elif cmd == 0x02:  # DATA
        return self._handle_data(fields)
    elif cmd == 0x03:  # DISCONNECT
        return self._handle_disconnect(fields)
    else:
        return self._build_error_response(b"Unknown command")
```

#### 3. **Response Crafting**

Use the response parser to build valid responses:

```python
def _build_response(self, fields: Dict[str, any]) -> bytes:
    # The response parser handles serialization
    return self.response_parser.serialize(fields)
```

### TCP Timeout Configuration

Set timeouts appropriately for your testing needs:

```python
client_sock.settimeout(1.0)  # Server-side timeout per recv()
```

**Recommendations:**
- **Verification/Validation Testing:** 0.5-1.0 seconds
- **Network Testing:** 2-5 seconds
- **Production:** 10-30 seconds

**Pair with fuzzer timeout:**
- Fuzzer timeout should be **2x server timeout** (e.g., 2s fuzzer, 1s server)

---

## UDP Template Guide

### Understanding UDP Datagram Handling

UDP is much simpler than TCP because:
- ✅ No connections to manage
- ✅ No deadlock issues
- ✅ Each `recvfrom()` gets exactly one complete message
- ✅ No framing complexity

However, UDP has limitations:
- ❌ No delivery guarantee (packets can be lost)
- ❌ No ordering guarantee (may arrive out of order)
- ❌ No automatic retransmission
- ❌ Datagrams can be duplicated

### UDP Template Customization Points

#### 1. **Maximum Datagram Size**

Set `MAX_DATAGRAM_SIZE` based on your network and protocol:

```python
# Conservative (safe for internet)
MAX_DATAGRAM_SIZE = 1472  # Ethernet MTU - headers

# Local network (typical)
MAX_DATAGRAM_SIZE = 8192

# Maximum possible (risky - causes fragmentation)
MAX_DATAGRAM_SIZE = 65507
```

**Fragmentation warning:** UDP datagrams larger than the network MTU will be fragmented by IP layer, which:
- Reduces reliability (one lost fragment = entire datagram lost)
- Increases latency
- May be blocked by firewalls

#### 2. **Message Processing**

Much simpler than TCP since you get complete datagrams:

```python
def _process_message(self, fields: Dict[str, any], addr: Tuple[str, int]) -> bytes:
    # Each datagram is independent
    cmd = fields.get("command")

    # Process based on command
    if cmd == "PING":
        return self._build_response({"response": "PONG"})
    elif cmd == "QUERY":
        return self._handle_query(fields)
    else:
        return self._build_error_response(b"Unknown command")
```

#### 3. **Session State (Optional)**

UDP is stateless, but you can track state per client if needed:

```python
# Track sessions by (ip, port) tuple
session_key = (client_ip, client_port)

if session_key not in self.sessions:
    self.sessions[session_key] = {
        "created": datetime.now(),
        "message_count": 0,
        "sequence_number": 0
    }

session = self.sessions[session_key]
session["message_count"] += 1
```

### UDP Idempotency Considerations

Since UDP can duplicate datagrams, make handlers idempotent when possible:

```python
def _handle_request(self, fields: Dict[str, any]) -> bytes:
    request_id = fields.get("request_id")

    # Check if we've already processed this request
    if request_id in self.processed_requests:
        # Return cached response
        return self.processed_requests[request_id]

    # Process new request
    response = self._process_new_request(fields)

    # Cache response for duplicates
    self.processed_requests[request_id] = response

    return response
```

---

## Common Patterns

### Pattern 1: Request-Response Protocol

**TCP Example:**
```python
def _process_message(self, fields: Dict[str, any], addr: tuple) -> bytes:
    request_id = fields.get("request_id")
    command = fields.get("command")

    # Process command
    result = self._execute_command(command)

    # Build response
    return self._build_response({
        "request_id": request_id,
        "status": "OK",
        "result": result
    })
```

**UDP Example:** Same logic, but simpler receive/send

### Pattern 2: Session-Based Protocol

**TCP Example:**
```python
def _handle_handshake(self, fields: Dict[str, any]) -> bytes:
    # Create session
    session_token = secrets.randbits(64)
    self.sessions[session_token] = {
        "state": "AUTHENTICATED",
        "created": datetime.now()
    }

    return self._build_response({
        "session_token": session_token,
        "status": "OK"
    })

def _handle_data(self, fields: Dict[str, any]) -> bytes:
    session_token = fields.get("session_token")

    # Validate session
    if session_token not in self.sessions:
        return self._build_error_response(b"Invalid session")

    # Process with session context
    return self._process_with_session(fields, self.sessions[session_token])
```

### Pattern 3: Multi-Message Protocol

For protocols that require multiple messages to complete a transaction:

```python
def _process_message(self, fields: Dict[str, any], addr: tuple) -> bytes:
    session_id = fields.get("session_id")
    msg_type = fields.get("message_type")

    # Get or create session state
    if session_id not in self.sessions:
        self.sessions[session_id] = {"state": "INIT", "data": {}}

    session = self.sessions[session_id]

    # State machine
    if session["state"] == "INIT" and msg_type == "START":
        session["state"] = "READY"
        return self._build_response({"status": "READY"})

    elif session["state"] == "READY" and msg_type == "DATA":
        session["data"][fields["key"]] = fields["value"]
        return self._build_response({"status": "ACCEPTED"})

    elif session["state"] == "READY" and msg_type == "COMMIT":
        self._commit_session(session["data"])
        session["state"] = "COMPLETE"
        return self._build_response({"status": "COMMITTED"})

    else:
        return self._build_error_response(
            f"Invalid msg_type {msg_type} in state {session['state']}".encode()
        )
```

---

## Troubleshooting

### TCP Issues

#### Problem: All tests timeout/hang
**Symptoms:**
- Fuzzer shows all tests as "hangs"
- Server logs show connections but no message processing

**Solution:**
- Check `_calculate_message_size()` - it might be incorrect
- Verify length field offsets match your protocol
- Add debug logging to see how much data is being read

```python
# Add debug logging
self._log("debug", f"Buffer size: {len(buffer)}, expected: {total_size}")
```

#### Problem: Parse errors
**Symptoms:**
- Server logs show "Parse error: ..."
- Fuzzer receives error responses

**Solution:**
- Verify `data_model` matches what fuzzer is sending
- Check endianness (big vs little endian)
- Validate field sizes and offsets

```python
# Debug: print raw bytes
self._log("debug", f"Raw bytes: {buffer.hex()}")
```

#### Problem: Slow test execution
**Symptoms:**
- Each test takes 3+ seconds
- Timeout warnings in logs

**Solution:**
- Reduce server timeout: `client_sock.settimeout(0.5)`
- Reduce fuzzer timeout: `"timeout_per_test_ms": 1500`
- Ensure you're not waiting for connection close

### UDP Issues

#### Problem: No responses received
**Symptoms:**
- Fuzzer shows 0 response bytes
- Server shows datagrams received but no sends

**Solution:**
- Check response size doesn't exceed `MAX_DATAGRAM_SIZE`
- Verify `sendto()` is being called
- Check for exceptions in `_send_response()`

```python
# Add logging
def _send_response(self, response: bytes, addr: Tuple[str, int]) -> None:
    self._log("debug", f"Sending {len(response)} bytes to {addr}")
    bytes_sent = self.server_socket.sendto(response, addr)
    self._log("debug", f"Actually sent: {bytes_sent} bytes")
```

#### Problem: Responses truncated
**Symptoms:**
- Response size is exactly `MAX_DATAGRAM_SIZE`
- Fuzzer shows incomplete responses

**Solution:**
- Increase `MAX_DATAGRAM_SIZE`
- Or reduce response size
- Or use TCP instead if messages are large

### General Debugging Tips

1. **Enable verbose logging:**
   ```python
   def _log(self, level: str, message: str) -> None:
       # Show debug logs
       if level == "debug":
           print(f"[DEBUG] {message}")  # Don't skip
   ```

2. **Inspect raw bytes:**
   ```python
   self._log("debug", f"Received hex: {data.hex()}")
   self._log("debug", f"Received repr: {data!r}")
   ```

3. **Test manually with netcat:**
   ```bash
   # TCP
   echo -ne '\x00\x00\x00\x0FHELLO' | nc localhost 9999 | xxd

   # UDP
   echo -ne '\x00\x00\x00\x0FHELLO' | nc -u localhost 9999 | xxd
   ```

4. **Check Docker networking:**
   ```bash
   # From container
   docker exec fuzzer-core nc -zv target 9999

   # From host to container
   nc -zv localhost 9999
   ```

5. **Monitor with tcpdump:**
   ```bash
   # Capture traffic on port 9999
   sudo tcpdump -i any -X port 9999
   ```

---

## Next Steps

1. ✅ Copy the appropriate template
2. ✅ Create your protocol plugin in `core/plugins/`
3. ✅ Customize the template following the `CUSTOMIZATION POINT` markers
4. ✅ Test manually with netcat
5. ✅ Run a fuzzing session
6. ✅ Verify responses are received correctly
7. ✅ Adjust timeouts for optimal performance

For more examples, see:
- `tests/feature_showcase_server.py` - Complex TCP protocol with state machine
- `tests/simple_tcp_server.py` - Simple TCP echo server

Happy fuzzing! 🐛
