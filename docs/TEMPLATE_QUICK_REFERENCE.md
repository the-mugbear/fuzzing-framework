# Protocol Server Templates - Quick Reference

## Files Created

| File | Purpose |
|------|---------|
| `tests/template_tcp_server.py` | TCP server template with intelligent message framing |
| `tests/template_udp_server.py` | UDP server template for datagram protocols |
| `docs/PROTOCOL_SERVER_TEMPLATES.md` | Comprehensive guide with examples and troubleshooting |
| `docs/TEMPLATE_QUICK_REFERENCE.md` | This quick reference card |

## Quick Start (30 seconds)

```bash
# 1. Copy template
cp tests/template_tcp_server.py tests/my_server.py

# 2. Edit customization points (search for "CUSTOMIZATION POINT")
#    - Import your protocol plugin
#    - Update _calculate_message_size()
#    - Implement _process_message()

# 3. Run server
python tests/my_server.py --port 9999

# 4. Test with fuzzer
curl -X POST http://localhost:8000/api/sessions -d '{"protocol":"my_protocol","target_host":"localhost","target_port":9999}'
```

## Critical Differences: TCP vs UDP

### TCP Template
- **Use for:** Connection-oriented, reliable protocols
- **Key method:** `_calculate_message_size()` - **YOU MUST CUSTOMIZE THIS!**
- **Critical:** Avoid deadlock by reading exact message size, not waiting for connection close
- **Complexity:** High (message framing required)

### UDP Template
- **Use for:** Connectionless, low-latency protocols
- **Key method:** `_process_message()` - simpler than TCP
- **Critical:** Set correct `MAX_DATAGRAM_SIZE` to avoid fragmentation
- **Complexity:** Low (datagrams are naturally framed)

## The #1 TCP Mistake (Deadlock)

**❌ WRONG - Will deadlock with fuzzer:**
```python
while True:
    chunk = sock.recv(4096)
    if not chunk:  # Waits for client close
        break
```

**✅ CORRECT - Read exact message:**
```python
# Read header with length field
header = read_exactly(sock, 20)
msg_len = struct.unpack('>I', header[16:20])[0]

# Read exact message bytes
data = read_exactly(sock, msg_len)

# Process and respond IMMEDIATELY
response = process(data)
sock.sendall(response)
```

## Essential Customization Points (In Order)

### Both Templates

1. **Import protocol:**
   ```python
   from core.plugins import my_protocol
   ```

2. **Initialize parser:**
   ```python
   self.request_parser = ProtocolParser(my_protocol.data_model)
   ```

3. **Process messages:**
   ```python
   def _process_message(self, fields, addr):
       # Your protocol logic here
       return self._build_response({...})
   ```

### TCP Only (Most Important!)

4. **Calculate message size:**
   ```python
   def _calculate_message_size(self, buffer, sock):
       # Parse length from YOUR protocol's header
       length = struct.unpack('>I', buffer[OFFSET:OFFSET+4])[0]
       return HEADER_SIZE + length + TRAILER_SIZE
   ```

### UDP Only

4. **Set max datagram size:**
   ```python
   MAX_DATAGRAM_SIZE = 8192  # Adjust for your needs
   ```

## Timeout Configuration

| Scenario | Server Timeout | Fuzzer Timeout | Speed |
|----------|---------------|----------------|-------|
| **Verification Testing** | 0.5-1.0s | 1.5-2.0s | ⚡ Fast |
| **Network Testing** | 2-5s | 5-10s | 🐢 Slower |
| **Production** | 10-30s | 30-60s | 🐌 Slowest |

**Rule of thumb:** Fuzzer timeout = 2× server timeout

## Testing Your Server

### Manual Test (TCP)
```bash
# Send raw bytes
echo -ne '\x4D\x59\x50\x4B\x00\x0A\x48\x45\x4C\x4C\x4F' | nc localhost 9999 | xxd
```

### Manual Test (UDP)
```bash
# Send UDP datagram
echo -ne '\x4D\x59\x50\x4B\x00\x0A\x48\x45\x4C\x4C\x4F' | nc -u localhost 9999 | xxd
```

### With Fuzzer
```bash
# Create session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"protocol":"my_protocol","target_host":"localhost","target_port":9999,"timeout_per_test_ms":2000}' \
  | jq -r '.id')

# Start fuzzing
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start"

# Check results (wait 10s)
sleep 10
curl "http://localhost:8000/api/sessions/$SESSION_ID" | jq '{total_tests,crashes,hangs,anomalies}'
```

## Common Issues & Fixes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| All tests hang (TCP) | Deadlock - waiting for close | Fix `_calculate_message_size()` |
| Parse errors | Wrong offsets/endianness | Check `data_model` matches actual bytes |
| No responses (UDP) | Response too large | Reduce size or increase `MAX_DATAGRAM_SIZE` |
| Slow execution | Timeouts too long | Reduce server + fuzzer timeouts |
| Connection refused | Server not running | Check `docker-compose ps` or `nc -zv` |

## Debug Checklist

- [ ] Server starts without errors
- [ ] Manual netcat test gets response
- [ ] Fuzzer connects (check server logs)
- [ ] Fuzzer receives responses (not all hangs)
- [ ] Parse succeeds (no parse errors in logs)
- [ ] Tests complete in <2 seconds
- [ ] State coverage > 25% (for stateful protocols)

## Example Protocol Structures

### Simple Length-Prefixed (TCP)
```
[Magic: 4 bytes][Length: 4 bytes][Payload: N bytes]
```

**Message size calculation:**
```python
length = struct.unpack('>I', buffer[4:8])[0]
return 8 + length  # header + payload
```

### Header + Payload + Trailer (TCP)
```
[Header: 20 bytes][Payload_len: 4 bytes][Payload: N bytes][Checksum: 4 bytes]
```

**Message size calculation:**
```python
payload_len = struct.unpack('>I', buffer[20:24])[0]
return 24 + payload_len + 4  # header + payload + checksum
```

### Command + Data (UDP)
```
[Command: 1 byte][Flags: 1 byte][Data: N bytes]
```

**No size calculation needed** - UDP datagrams are self-delimiting!

## Resources

- **Full Guide:** `docs/PROTOCOL_SERVER_TEMPLATES.md`
- **TCP Example:** `tests/feature_showcase_server.py`
- **Simple Example:** `tests/simple_tcp_server.py`
- **Your Protocol:** Create in `core/plugins/my_protocol.py`

## Getting Help

1. Read inline comments in template (100+ lines of docs)
2. Check `docs/PROTOCOL_SERVER_TEMPLATES.md` for detailed examples
3. Look at `tests/feature_showcase_server.py` for complex patterns
4. Enable debug logging to see what's happening:
   ```python
   def _log(self, level, message):
       print(f"[{level}] {message}")  # Show all logs
   ```

---

**Remember:** The template comments are your friend! Every customization point is clearly marked and explained. When in doubt, read the comments. 📖
