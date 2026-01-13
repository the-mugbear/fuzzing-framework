# Protocol Testing Guide

Complete guide for creating, testing, and validating custom protocol plugins for the fuzzer.

## Table of Contents

1. [Overview](#overview)
2. [Creating a Protocol Plugin](#creating-a-protocol-plugin)
3. [Testing Your Protocol](#testing-your-protocol)
4. [Validation Strategies](#validation-strategies)
5. [Debugging Protocol Issues](#debugging-protocol-issues)
6. [Advanced Testing Techniques](#advanced-testing-techniques)
7. [Best Practices](#best-practices)

---

## Overview

This guide walks you through the complete process of:
1. Creating a protocol plugin
2. Testing it with a real target
3. Validating the fuzzer correctly mutates your protocol
4. Debugging issues
5. Optimizing for maximum coverage

## Creating a Protocol Plugin

### Step 1: Understand Your Protocol

Before writing code, document:
- **Message structure**: What fields exist? What are their types and sizes?
- **State machine**: Does the protocol have states? What transitions exist?
- **Valid examples**: Collect 3-5 valid protocol messages
- **Error conditions**: What responses indicate errors?

**Example analysis for a financial protocol**:
```
Message Structure:
- Magic header: "BANK" (4 bytes)
- Version: uint8 (1 byte)
- Command: uint8 (1 byte)
- Length: uint32 big-endian (4 bytes)
- Payload: variable bytes

States:
- DISCONNECTED → CONNECTED (via CONNECT)
- CONNECTED → AUTHENTICATED (via AUTH)
- AUTHENTICATED → READY (via LOGIN)

Valid example:
BANK\x01\x02\x00\x00\x00\x04TEST
```

### Step 2: Create the Plugin File

Create `core/plugins/your_protocol.py`:

```python
"""
Your protocol plugin.

- Purpose: Financial transaction protocol for internal testing.
- Transport: TCP.
- Includes: Seeds + basic state machine.
"""

__version__ = "1.0.0"

# Docstring format guidance:
# - First line: short summary sentence.
# - Blank line.
# - Bullet list with 2-4 items that explain purpose, transport, and notable features.
# The Plugin Debugger surfaces this docstring as the plugin description.

# ==================== Data Model ====================

data_model = {
    "name": "YourProtocol",
    "description": "Financial transaction protocol",
    "version": "1.0.0",

    "blocks": [
        # Header (don't mutate magic bytes)
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"BANK",
            "mutable": False,  # Prevent fuzzer from changing this
            "description": "Protocol magic header"
        },

        # Version field
        {
            "name": "version",
            "type": "uint8",
            "default": 1,
            "values": {
                1: "Version 1.0",
                2: "Version 2.0"
            }
        },

        # Command type
        {
            "name": "command",
            "type": "uint8",
            "default": 1,
            "values": {
                1: "CONNECT",
                2: "AUTH",
                3: "TRANSFER",
                4: "BALANCE",
                5: "LOGOUT"
            }
        },

        # Length field (linked to payload size)
        {
            "name": "length",
            "type": "uint32",
            "endian": "big",
            "is_size_field": True,
            "size_of": "payload",
            "description": "Payload length in bytes"
        },

        # Variable-length payload
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 1024,
            "description": "Command-specific data"
        }
    ],

    # Seed corpus: Valid protocol messages
    "seeds": [
        # CONNECT message
        b"BANK\x01\x01\x00\x00\x00\x00",

        # AUTH message with credentials
        b"BANK\x01\x02\x00\x00\x00\x10admin:password123",

        # BALANCE request
        b"BANK\x01\x04\x00\x00\x00\x00",

        # TRANSFER with amount
        b"BANK\x01\x03\x00\x00\x00\x08\x00\x00\x03\xe8TO:1234",
    ]
}

#### Sub-Byte Fields (Bits)

For protocols with bit-level fields (IPv4, DNS, Bluetooth, CAN bus, etc.), use the `bits` type to define fields smaller than a byte:

**Basic Bit Fields**

```python
data_model = {
    "blocks": [
        # 4-bit version field (nibble)
        {"name": "version", "type": "bits", "size": 4, "default": 0x4},

        # 4-bit header length
        {"name": "ihl", "type": "bits", "size": 4, "default": 0x5},

        # Single bit flag
        {"name": "flag_urgent", "type": "bits", "size": 1, "default": 0},

        # 3-bit field
        {"name": "flags", "type": "bits", "size": 3, "default": 0x0},

        # 13-bit field (spans byte boundary)
        {"name": "fragment_offset", "type": "bits", "size": 13, "default": 0x0},
    ]
}
```

**Key Features:**
- **Size range**: 1-64 bits per field
- **Byte spanning**: Bit fields can cross byte boundaries
- **Auto-alignment**: Integer types (`uint*`, `int*`) automatically align to byte boundaries after bit fields
- **Masking**: Values are automatically masked to the specified bit width

**Bit Ordering**

By default, bits are read MSB-first (most significant bit first - network order). For LSB-first protocols:

```python
{
    "name": "field",
    "type": "bits",
    "size": 4,
    "bit_order": "lsb"  # Least significant bit first
}
```

**Multi-Byte Bit Field Endianness**

For bit fields spanning multiple bytes (>8 bits), specify byte order:

```python
{
    "name": "fragment_id",
    "type": "bits",
    "size": 12,
    "endian": "big"  # Default: big-endian (network order)
}

{
    "name": "value",
    "type": "bits",
    "size": 12,
    "endian": "little"  # Little-endian if needed
}
```

**Size Fields with Bits**

Size fields can count in bits, bytes, or words:

```python
{
    "name": "length",
    "type": "uint16",
    "is_size_field": True,
    "size_of": ["payload"],
    "size_unit": "bits"  # Options: "bits", "bytes" (default), "words" (32-bit), "dwords" (16-bit)
}
```

**Example: IPv4-Style Header**

```python
data_model = {
    "name": "IPv4Header",
    "blocks": [
        # Version (4 bits) + IHL (4 bits)
        {"name": "version", "type": "bits", "size": 4, "default": 0x4, "mutable": False},
        {"name": "ihl", "type": "bits", "size": 4, "default": 0x5},  # Header length in 32-bit words

        # DSCP (6 bits) + ECN (2 bits)
        {"name": "dscp", "type": "bits", "size": 6, "default": 0x0},
        {"name": "ecn", "type": "bits", "size": 2, "default": 0x0},

        # Total length (auto-calculated)
        {
            "name": "total_length",
            "type": "uint16",
            "endian": "big",
            "is_size_field": True,
            "size_of": ["header", "payload"],
            "size_unit": "bytes"
        },

        # Identification
        {"name": "identification", "type": "uint16", "endian": "big", "default": 0x0},

        # Flags (3 bits) + Fragment Offset (13 bits)
        {"name": "flags", "type": "bits", "size": 3, "default": 0x0},
        {"name": "fragment_offset", "type": "bits", "size": 13, "default": 0x0},

        # Remaining fields (byte-aligned)
        {"name": "ttl", "type": "uint8", "default": 64},
        {"name": "protocol", "type": "uint8", "default": 6},  # TCP
        {"name": "checksum", "type": "uint16", "endian": "big", "default": 0x0},
        {"name": "src_ip", "type": "bytes", "size": 4, "default": b"\xC0\xA8\x01\x01"},
        {"name": "dst_ip", "type": "bytes", "size": 4, "default": b"\xC0\xA8\x01\x02"},
        {"name": "payload", "type": "bytes", "max_size": 1480},
    ],
    "seeds": []  # Auto-generated from defaults
}
```

**Bit Field Mutations**

The mutation engine automatically handles bit fields:
- **Boundary values**: Tests 0, 1, max, max-1, mid-point
- **Interesting values**: Tests all-zeros, all-ones, power-of-2 patterns
- **Arithmetic**: Adds/subtracts small values with proper masking
- **Bit flips**: Flips individual bits within the field

**Response Extraction from Bit Fields**

Extract specific bit ranges from response fields:

```python
# In stateful plugins, extract bits from response
{
    "name": "status_code",
    "copy_from_response": "response_flags",
    "extract_bits": {
        "start": 4,  # Start at bit 4
        "count": 4   # Extract 4 bits
    }
}
```

### Step 3: Add Field Behaviors (Optional but Recommended)

Use the `behavior` key when a block must follow deterministic rules even while other bytes are fuzzed. Behaviors run before each test case is transmitted in both core and agent modes.

```python
{
    "name": "sequence",
    "type": "uint16",
    "behavior": {
        "operation": "increment",   # auto-increment on every send
        "initial": 0,                 # starting value
        "step": 1,                    # optional increment size
        "wrap": 65536                 # optional wrap-around
    }
},
{
    "name": "checksum",
    "type": "uint8",
    "behavior": {
        "operation": "add_constant",
        "value": 0x55                 # add before sending (mod field size)
    }
}
```

Supported operations today:
- `increment`: Write the current counter value, then advance it using `step`/`wrap`.
- `add_constant`: Add/substitute a constant to the existing field value before transmission.

Behaviors require fixed-width fields (bytes with `size`, uint16/32/64, etc.). They remove the need for custom mutators to keep sequence numbers, checksums, or derived counters valid and ensure the target continues accepting fuzzed packets.

# ==================== State Model ====================

state_model = {
    "initial_state": "DISCONNECTED",

    "states": [
        "DISCONNECTED",
        "CONNECTED",
        "AUTHENTICATED",
        "READY"
    ],

    "transitions": [
        {
            "from": "DISCONNECTED",
            "to": "CONNECTED",
            "trigger": "connect",
            "message_type": "CONNECT",
            "expected_response": "CONNECT_OK"
        },
        {
            "from": "CONNECTED",
            "to": "AUTHENTICATED",
            "trigger": "authenticate",
            "message_type": "AUTH",
            "expected_response": "AUTH_OK"
        },
        {
            "from": "AUTHENTICATED",
            "to": "READY",
            "trigger": "login",
            "message_type": "LOGIN",
            "expected_response": "LOGIN_OK"
        }
    ]
}

# ==================== Validator (Specification Oracle) ====================

def validate_response(response: bytes) -> bool:
    """
    Custom response validation - your "specification oracle"

    This function checks if the server's response violates protocol rules.
    It's NOT about checking if the server crashed - that's automatic.
    This is about detecting LOGICAL bugs that wouldn't cause a crash.

    Args:
        response: Raw response bytes from target

    Returns:
        True if response is valid per spec
        False if response violates protocol rules (logical bug found!)

    Raises:
        ValueError: For severe violations with descriptive messages
    """

    # Must have at least header + version + command + length
    if len(response) < 10:
        return False

    # Verify magic header
    if response[:4] != b"BANK":
        return False

    # Version must be 1 or 2
    version = response[4]
    if version not in (1, 2):
        return False

    # Command must be valid
    command = response[5]
    if command < 1 or command > 5:
        return False

    # Check length field matches payload
    import struct
    length = struct.unpack(">I", response[6:10])[0]
    actual_payload_len = len(response) - 10

    if length != actual_payload_len:
        # Length mismatch - potential buffer overflow!
        return False

    # Example: Check for business logic bugs
    if command == 4:  # BALANCE response
        # Balance should never be negative
        if len(response) >= 14:
            balance = struct.unpack(">i", response[10:14])[0]
            if balance < 0:
                # Found a logic bug! Negative balance should be impossible
                raise ValueError(f"Negative balance detected: {balance}")

    return True
```

### Step 3: Install the Plugin

```bash
# Copy to plugins directory (if not already there)
cp your_protocol.py core/plugins/

# Restart the Core to load the plugin
docker-compose restart core

# Or if running locally
# Just restart the Python process - plugins are loaded on startup
```

### Step 4: Verify Plugin Loaded

```bash
# List all plugins
curl http://localhost:8000/api/plugins

# Get your protocol details
curl http://localhost:8000/api/plugins/your_protocol | jq .
```

Expected output:
```json
{
  "name": "YourProtocol",
  "data_model": { ... },
  "state_model": { ... },
  "description": "Financial transaction protocol",
  "version": "1.0.0"
}
```

---

## Testing Your Protocol

### Test 1: Manual Protocol Validation

Before fuzzing, ensure your protocol plugin generates valid messages.

#### Create a Test Script

Create `test_protocol.py`:

```python
#!/usr/bin/env python3
"""Test protocol message generation"""

import sys
sys.path.insert(0, '.')

from core.plugin_loader import plugin_manager

# Load your protocol
protocol = plugin_manager.load_plugin("your_protocol")

print(f"Protocol: {protocol.data_model['name']}")
print(f"Seeds: {len(protocol.data_model['seeds'])}")

# Test each seed
for i, seed in enumerate(protocol.data_model['seeds'], 1):
    print(f"\nSeed {i}:")
    print(f"  Length: {len(seed)} bytes")
    print(f"  Hex: {seed.hex()}")
    print(f"  ASCII: {seed[:50]}")  # First 50 bytes

    # Validate if validator exists
    if hasattr(protocol, 'validate_response'):
        # Note: This tests the seed as if it were a response
        # For proper testing, send to your target and validate the response
        print(f"  Has validator: Yes")
    else:
        print(f"  Has validator: No")
```

Run it:
```bash
python test_protocol.py
```

Expected output:
```
Protocol: YourProtocol
Seeds: 4

Seed 1:
  Length: 10 bytes
  Hex: 42414e4b010100000000
  ASCII: BANK......
  Has validator: Yes

...
```

### Test 2: Send Seeds to Your Target

Test that your protocol's seeds work with your actual target server.

#### Option A: Using netcat (simple binary protocols)

```bash
# Start your target server
./your_target_server

# Send seed 1
echo -ne '\x42\x41\x4e\x4b\x01\x01\x00\x00\x00\x00' | nc localhost 9999

# Or from a file
echo -ne '\x42\x41\x4e\x4b\x01\x01\x00\x00\x00\x00' > seed1.bin
nc localhost 9999 < seed1.bin
```

#### Option B: Using Python script

Create `test_target.py`:

```python
#!/usr/bin/env python3
"""Test target with protocol seeds"""

import socket
import sys
sys.path.insert(0, '.')

from core.plugin_loader import plugin_manager

# Configuration
TARGET_HOST = "localhost"
TARGET_PORT = 9999

# Load protocol
protocol = plugin_manager.load_plugin("your_protocol")

print(f"Testing {protocol.data_model['name']} against {TARGET_HOST}:{TARGET_PORT}")

# Test each seed
for i, seed in enumerate(protocol.data_model['seeds'], 1):
    print(f"\n[Seed {i}] Sending {len(seed)} bytes...")

    try:
        # Connect to target
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((TARGET_HOST, TARGET_PORT))

        # Send seed
        sock.sendall(seed)
        print(f"  ✓ Sent successfully")

        # Receive response
        response = sock.recv(4096)
        print(f"  ✓ Received {len(response)} bytes")
        print(f"  Response (hex): {response[:50].hex()}")

        # Validate response
        if hasattr(protocol, 'validate_response'):
            validator = protocol.validate_response
            try:
                is_valid = validator(response)
                if is_valid:
                    print(f"  ✓ Response is valid")
                else:
                    print(f"  ✗ Response is INVALID (logical bug!)")
            except Exception as e:
                print(f"  ✗ Validation error: {e}")

        sock.close()

    except socket.timeout:
        print(f"  ✗ Timeout (target hung?)")
    except ConnectionRefusedError:
        print(f"  ✗ Connection refused (is target running?)")
    except Exception as e:
        print(f"  ✗ Error: {e}")

print("\n✓ All seeds tested")
```

Run it:
```bash
python test_target.py
```

Expected output:
```
Testing YourProtocol against localhost:9999

[Seed 1] Sending 10 bytes...
  ✓ Sent successfully
  ✓ Received 14 bytes
  Response (hex): 42414e4b01010000000a434f4e4e4543545f4f4b
  ✓ Response is valid

[Seed 2] Sending 26 bytes...
  ✓ Sent successfully
  ✓ Received 18 bytes
  Response (hex): 42414e4b01020000000c415554485f4f4b
  ✓ Response is valid

✓ All seeds tested
```

### Test 3: Create a Fuzzing Session

Now test with the actual fuzzer:

```bash
# Create session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "protocol": "your_protocol",
    "target_host": "localhost",
    "target_port": 9999
  }' | jq -r '.id')

echo "Session ID: $SESSION_ID"

# Start fuzzing
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start"

# Let it run for 10 seconds
sleep 10

# Stop fuzzing
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/stop"

# Check results
curl "http://localhost:8000/api/sessions/$SESSION_ID" | jq '{
  status: .status,
  total_tests: .total_tests,
  crashes: .crashes,
  hangs: .hangs,
  anomalies: .anomalies,
  error_message: .error_message
}'
```

Expected output:
```json
{
  "status": "completed",
  "total_tests": 1523,
  "crashes": 2,
  "hangs": 1,
  "anomalies": 47,
  "error_message": null
}
```

### Test 4: Verify Mutations Are Working

Check that the fuzzer is actually mutating your protocol messages:

```bash
# Enable debug logging (in docker-compose.yml, set LOG_LEVEL=DEBUG)
docker-compose restart core

# Watch mutations in real-time
docker-compose logs -f core | grep mutation

# Or check a finding to see mutated input
FINDING_ID=$(curl -s http://localhost:8000/api/corpus/findings | jq -r '.findings[0]')
curl "http://localhost:8000/api/corpus/findings/$FINDING_ID" | jq '.report.reproducer_data' | xxd
```

You should see messages that are variations of your seeds with bit flips, byte changes, etc.

---

## Validation Strategies

### Strategy 1: Basic Structural Validation

Ensures responses have correct structure:

```python
def validate_response(response: bytes) -> bool:
    """Check basic protocol structure"""
    # Minimum size
    if len(response) < 10:
        return False

    # Magic header
    if response[:4] != b"MYPK":
        return False

    # Version field in range
    if response[4] not in (1, 2, 3):
        return False

    return True
```

### Strategy 2: Length Field Validation

Detects buffer overflows and underflows:

```python
def validate_response(response: bytes) -> bool:
    """Check length fields match actual data"""
    import struct

    if len(response) < 8:
        return False

    # Extract length field
    declared_length = struct.unpack(">I", response[4:8])[0]
    actual_length = len(response) - 8

    if declared_length != actual_length:
        # Length mismatch = potential overflow
        return False

    return True
```

### Strategy 3: Business Logic Validation

Catches semantic bugs:

```python
def validate_response(response: bytes) -> bool:
    """Check business rules"""
    import struct

    if len(response) < 10:
        return False

    command = response[5]

    # BALANCE command
    if command == 4 and len(response) >= 14:
        balance = struct.unpack(">i", response[10:14])[0]

        # Business rule: balance cannot be negative
        if balance < 0:
            raise ValueError(f"Invalid balance: {balance}")

        # Business rule: balance cannot exceed max
        if balance > 1000000:
            raise ValueError(f"Balance too large: {balance}")

    # TRANSFER command
    if command == 3 and len(response) >= 14:
        amount = struct.unpack(">i", response[10:14])[0]

        # Transfer amount must be positive
        if amount <= 0:
            raise ValueError(f"Invalid transfer amount: {amount}")

    return True
```

### Strategy 4: State Machine Validation

Enforces protocol state transitions:

```python
# Global state (in production, use session-based state)
current_state = "DISCONNECTED"

def validate_response(response: bytes) -> bool:
    """Validate state transitions"""
    global current_state

    if len(response) < 10:
        return False

    command = response[5]
    response_code = response[9]  # 0 = OK, 1 = ERROR

    # Can only AUTH if CONNECTED
    if command == 2 and current_state != "CONNECTED":
        raise ValueError(f"AUTH in wrong state: {current_state}")

    # Can only TRANSFER if AUTHENTICATED
    if command == 3 and current_state != "AUTHENTICATED":
        raise ValueError(f"TRANSFER in wrong state: {current_state}")

    # Update state on successful response
    if response_code == 0:
        if command == 1:  # CONNECT
            current_state = "CONNECTED"
        elif command == 2:  # AUTH
            current_state = "AUTHENTICATED"

    return True
```

---

## Debugging Protocol Issues

### Issue 1: Plugin Not Loading

**Symptoms**:
```bash
$ curl http://localhost:8000/api/plugins
[]  # Empty list
```

**Debug steps**:
```bash
# Check plugin file exists
ls -la core/plugins/your_protocol.py

# Check for syntax errors
python -m py_compile core/plugins/your_protocol.py

# Check Core logs
docker-compose logs core | grep -i "plugin\|error"

# Test import directly
python -c "from core.plugins import your_protocol; print(your_protocol.data_model)"
```

### Issue 2: No Mutations Happening

**Symptoms**:
- `total_tests` stays at 0
- No logs showing test execution

**Debug steps**:
```bash
# Check session status
curl http://localhost:8000/api/sessions/$SESSION_ID | jq '.status, .error_message'

# Check if seeds are loaded
curl http://localhost:8000/api/corpus/seeds | jq '.seed_ids'

# Verify target is reachable
nc -zv localhost 9999

# Check Docker networking (if in Docker)
docker exec fuzzer-core ping -c 1 target
```

### Issue 3: All Tests Marked as Crashes

**Symptoms**:
```json
{
  "total_tests": 100,
  "crashes": 100,
  "hangs": 0
}
```

**Possible causes**:
1. Target not running
2. Wrong port
3. Connection refused

**Debug**:
```bash
# Check target is running
docker-compose ps
docker-compose logs target

# Test target manually
echo "test" | nc localhost 9999

# Check Core can reach target
docker exec fuzzer-core nc -zv target 9999
```

### Issue 4: Validator Always Returns False

**Symptoms**:
```json
{
  "anomalies": 1000,  # Very high
  "crashes": 0
}
```

**Debug**:
```python
# Add debug logging to validator
def validate_response(response: bytes) -> bool:
    print(f"[DEBUG] Validating {len(response)} bytes: {response[:20].hex()}")

    if len(response) < 4:
        print("[DEBUG] Too short")
        return False

    if response[:4] != b"MYPK":
        print(f"[DEBUG] Wrong magic: {response[:4]}")
        return False

    print("[DEBUG] Valid!")
    return True
```

Run fuzzing and check logs:
```bash
docker-compose logs -f core | grep DEBUG
```

---

## Advanced Testing Techniques

### Technique 1: Monitoring Target Behavior

Watch your target while fuzzing:

```bash
# Terminal 1: Watch target logs
docker-compose logs -f target

# Terminal 2: Monitor resource usage
watch 'docker stats target --no-stream'

# Terminal 3: Run fuzzing session
curl -X POST http://localhost:8000/api/sessions/$SESSION_ID/start
```

### Technique 2: Comparing Mutations

Extract and compare mutated inputs:

```bash
# Get all findings
curl -s http://localhost:8000/api/corpus/findings | jq -r '.findings[]' > findings.txt

# Download each finding
while read finding_id; do
  curl -s "http://localhost:8000/api/corpus/findings/$finding_id" | \
    jq -r '.reproducer_data' | base64 -d > "finding_${finding_id}.bin"
done < findings.txt

# Compare to original seeds
xxd finding_*.bin
xxd core/plugins/your_protocol.py  # Check seeds
```

### Technique 3: Targeted Field Fuzzing

Test specific fields by creating focused seeds:

```python
# In your protocol plugin, add seeds targeting specific fields

data_model = {
    "seeds": [
        # Normal seed
        b"MYPK\x01\x01\x00\x00\x00\x00",

        # Large length field (test buffer overflow)
        b"MYPK\x01\x01\xff\xff\xff\xff" + b"A" * 100,

        # Zero length (test underflow)
        b"MYPK\x01\x01\x00\x00\x00\x00",

        # Invalid command codes
        b"MYPK\x01\xff\x00\x00\x00\x00",

        # Maximum size payload
        b"MYPK\x01\x01\x00\x00\x04\x00" + b"A" * 1024,
    ]
}
```

### Technique 4: Performance Testing

Measure fuzzing throughput:

```bash
# Start session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"protocol": "your_protocol", "target_host": "target", "target_port": 9999}' | jq -r '.id')

curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start"

# Sample stats every second for 10 seconds
for i in {1..10}; do
  sleep 1
  TESTS=$(curl -s "http://localhost:8000/api/sessions/$SESSION_ID" | jq '.total_tests')
  echo "Second $i: $TESTS tests"
done

# Stop and calculate rate
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/stop"
FINAL=$(curl -s "http://localhost:8000/api/sessions/$SESSION_ID" | jq '.total_tests')
echo "Rate: $((FINAL / 10)) tests/sec"
```

---

## Best Practices

### 1. Start Simple, Iterate

```python
# Version 1: Minimal viable protocol
data_model = {
    "blocks": [
        {"name": "header", "type": "bytes", "size": 4, "default": b"TEST"}
    ],
    "seeds": [b"TEST"]
}

# Version 2: Add structure
data_model = {
    "blocks": [
        {"name": "header", "type": "bytes", "size": 4, "default": b"TEST"},
        {"name": "command", "type": "uint8"}
    ],
    "seeds": [b"TEST\x01", b"TEST\x02"]
}

# Version 3: Add validation
def validate_response(response: bytes) -> bool:
    return len(response) >= 4 and response[:4] == b"TEST"
```

### 2. Use High-Quality Seeds

Good seeds increase coverage:

```python
"seeds": [
    # Minimum valid message
    b"HDR\x00",

    # Normal message
    b"HDR\x01\x00\x00\x00\x05HELLO",

    # Large message (tests boundaries)
    b"HDR\x02\x00\x00\x03\xe8" + b"X" * 1000,

    # Edge case (empty payload)
    b"HDR\x03\x00\x00\x00\x00",

    # Different states (if stateful)
    b"HDR\x10\x00\x00\x00\x04AUTH",  # AUTH state
    b"HDR\x20\x00\x00\x00\x04DATA",  # DATA state
]
```

### 3. Test Incrementally

After each change, verify:

```bash
# 1. Plugin loads
curl http://localhost:8000/api/plugins/your_protocol

# 2. Seeds are valid
python test_target.py

# 3. Short fuzzing run works
# (5 seconds to catch immediate issues)
./quick_fuzz_test.sh

# 4. Long run finds issues
# (1+ hours for real bugs)
./long_fuzz_test.sh
```

### 4. Document Your Protocol

```python
"""
Financial Protocol Plugin

Protocol Specification:
- RFC: internal-rfc-1234
- Version: 2.1
- Port: 9000

Message Format:
+--------+--------+--------+--------+--------+
| Magic  | Ver    | Cmd    | Length | Payload|
| (4B)   | (1B)   | (1B)   | (4B)   | (var)  |
+--------+--------+--------+--------+--------+

States:
- INIT: Initial connection
- AUTH: After successful authentication
- READY: Ready for transactions

Known Issues:
- Command 0xFF causes crash (CVE-2024-1234)
- Length > 65535 causes buffer overflow

Test Coverage:
- ✓ All commands tested
- ✓ State transitions validated
- ✓ Boundary conditions checked
- ⚠ Large payload handling (work in progress)
"""
```

### 5. Monitor and Tune

Track fuzzing effectiveness:

```bash
# Coverage over time
echo "Time,Tests,Crashes,Anomalies" > fuzzing_stats.csv
for hour in {1..24}; do
  sleep 3600
  STATS=$(curl -s http://localhost:8000/api/sessions/$SESSION_ID)
  echo "$hour,$(echo $STATS | jq -r '.total_tests,.crashes,.anomalies' | tr '\n' ',')" >> fuzzing_stats.csv
done

# Analyze results
cat fuzzing_stats.csv
```

If you see:
- **Low test count**: Target too slow, add more agents
- **No crashes/anomalies**: Seeds may not be diverse enough
- **Too many anomalies**: Validator may be too strict

---

## Quick Reference: Testing Checklist

- [ ] Protocol plugin created in `core/plugins/`
- [ ] Plugin loads successfully (`/api/plugins`)
- [ ] Seeds are structurally valid
- [ ] Seeds work with actual target (manual test)
- [ ] Fuzzing session can be created
- [ ] Fuzzing generates test cases (total_tests > 0)
- [ ] Validator detects logical bugs (if implemented)
- [ ] Findings are saved and reproducible
- [ ] Target doesn't crash on valid seeds
- [ ] Fuzzer finds known vulnerabilities (if any)

---

## Example: Complete Testing Workflow

```bash
#!/bin/bash
# complete_protocol_test.sh

set -e

PROTOCOL="your_protocol"
TARGET_HOST="localhost"
TARGET_PORT="9999"

echo "=== Protocol Testing Workflow ==="
echo

# Step 1: Verify plugin
echo "[1/6] Verifying plugin loads..."
curl -sf http://localhost:8000/api/plugins/$PROTOCOL > /dev/null
echo "✓ Plugin loaded"

# Step 2: Test seeds manually
echo "[2/6] Testing seeds against target..."
python test_target.py
echo "✓ Seeds validated"

# Step 3: Create fuzzing session
echo "[3/6] Creating fuzzing session..."
SESSION_ID=$(curl -sf -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d "{
    \"protocol\": \"$PROTOCOL\",
    \"target_host\": \"$TARGET_HOST\",
    \"target_port\": $TARGET_PORT
  }" | jq -r '.id')
echo "✓ Session created: $SESSION_ID"

# Step 4: Run short fuzzing campaign
echo "[4/6] Running 30-second fuzzing test..."
curl -sf -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start" > /dev/null
sleep 30
curl -sf -X POST "http://localhost:8000/api/sessions/$SESSION_ID/stop" > /dev/null
echo "✓ Fuzzing completed"

# Step 5: Check results
echo "[5/6] Analyzing results..."
STATS=$(curl -sf "http://localhost:8000/api/sessions/$SESSION_ID")
TOTAL=$(echo $STATS | jq -r '.total_tests')
CRASHES=$(echo $STATS | jq -r '.crashes')
ANOMALIES=$(echo $STATS | jq -r '.anomalies')
ERROR=$(echo $STATS | jq -r '.error_message')

echo "  Total tests: $TOTAL"
echo "  Crashes: $CRASHES"
echo "  Anomalies: $ANOMALIES"

if [ "$ERROR" != "null" ]; then
  echo "  ✗ Error: $ERROR"
  exit 1
fi

if [ "$TOTAL" -eq 0 ]; then
  echo "  ✗ No tests executed!"
  exit 1
fi

echo "✓ Results look good"

# Step 6: Verify findings are accessible
echo "[6/6] Checking findings..."
FINDINGS=$(curl -sf http://localhost:8000/api/corpus/findings | jq -r '.count')
echo "  Findings: $FINDINGS"
echo "✓ Findings accessible"

echo
echo "=== All Tests Passed ==="
echo
echo "Your protocol is ready for fuzzing!"
echo "Run a longer campaign with:"
echo "  curl -X POST http://localhost:8000/api/sessions/$SESSION_ID/start"
```

Save as `complete_protocol_test.sh`, make executable, and run:

```bash
chmod +x complete_protocol_test.sh
./complete_protocol_test.sh
```

---

## Support

- **Documentation**: See `README.md`, `QUICKSTART.md`, `CHEATSHEET.md`
- **Examples**: Check `core/plugins/simple_tcp.py` for a complete example
- **Issues**: Report bugs on GitHub
- **Community**: Join discussions for fuzzing best practices

Happy fuzzing! 🐛🔍
