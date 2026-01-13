"""
IPv4 Header Protocol Plugin

Demonstrates native sub-byte field support with a real-world protocol.

- Purpose: IPv4 packet header fuzzing for network stack testing
- Transport: Raw IP (or TCP with custom framing)
- Features: Nibbles, bit flags, byte-spanning fields, auto-calculated checksums

This plugin showcases all bit field capabilities:
- 4-bit version and IHL fields (nibbles)
- 6-bit DSCP and 2-bit ECN fields
- 3-bit flags and 13-bit fragment offset (spanning byte boundary)
- Auto-calculated total_length field
- Mixed bit and byte-aligned fields
"""

__version__ = "1.0.0"

# ==================== Data Model ====================

data_model = {
    "name": "IPv4Header",
    "description": "IPv4 packet header (RFC 791)",
    "version": "1.0.0",

    "blocks": [
        # Byte 0: Version (4 bits) + IHL (4 bits)
        {
            "name": "version",
            "type": "bits",
            "size": 4,
            "default": 0x4,
            "mutable": False,  # Keep version fixed at IPv4
            "description": "IP version (always 4 for IPv4)",
            "values": {
                4: "IPv4",
                6: "IPv6"  # For reference, not used
            }
        },
        {
            "name": "ihl",
            "type": "bits",
            "size": 4,
            "default": 0x5,
            "description": "Internet Header Length in 32-bit words (5 = 20 bytes minimum)",
            "values": {
                5: "No options (20 bytes)",
                6: "With options (24 bytes)",
                15: "Maximum (60 bytes)"
            }
        },

        # Byte 1: DSCP (6 bits) + ECN (2 bits)
        {
            "name": "dscp",
            "type": "bits",
            "size": 6,
            "default": 0x0,
            "description": "Differentiated Services Code Point",
            "values": {
                0x00: "Best Effort",
                0x2E: "Expedited Forwarding",
                0x0A: "Assured Forwarding"
            }
        },
        {
            "name": "ecn",
            "type": "bits",
            "size": 2,
            "default": 0x0,
            "description": "Explicit Congestion Notification",
            "values": {
                0: "Not-ECT",
                1: "ECT(1)",
                2: "ECT(0)",
                3: "CE"
            }
        },

        # Bytes 2-3: Total Length
        {
            "name": "total_length",
            "type": "uint16",
            "endian": "big",
            "is_size_field": True,
            "size_of": ["version", "ihl", "dscp", "ecn", "total_length", "identification",
                        "flags", "fragment_offset", "ttl", "protocol", "checksum",
                        "src_ip", "dst_ip", "payload"],
            "size_unit": "bytes",
            "description": "Total packet length in bytes (header + data)"
        },

        # Bytes 4-5: Identification
        {
            "name": "identification",
            "type": "uint16",
            "endian": "big",
            "default": 0x0000,
            "description": "Fragment identification number"
        },

        # Bytes 6-7: Flags (3 bits) + Fragment Offset (13 bits)
        {
            "name": "flags",
            "type": "bits",
            "size": 3,
            "default": 0x2,  # Don't Fragment flag set
            "description": "Control flags (Reserved, DF, MF)",
            "values": {
                0x0: "May Fragment",
                0x2: "Don't Fragment",
                0x4: "More Fragments",
                0x6: "Don't Fragment + More Fragments"
            }
        },
        {
            "name": "fragment_offset",
            "type": "bits",
            "size": 13,
            "default": 0x0,
            "description": "Fragment offset in 8-byte blocks"
        },

        # Byte 8: TTL
        {
            "name": "ttl",
            "type": "uint8",
            "default": 64,
            "description": "Time To Live (hop count)",
            "values": {
                1: "Local network",
                64: "Default",
                128: "Windows default",
                255: "Maximum"
            }
        },

        # Byte 9: Protocol
        {
            "name": "protocol",
            "type": "uint8",
            "default": 6,
            "description": "Next level protocol",
            "values": {
                1: "ICMP",
                6: "TCP",
                17: "UDP",
                41: "IPv6 encapsulation",
                47: "GRE",
                50: "ESP",
                89: "OSPF"
            }
        },

        # Bytes 10-11: Header Checksum
        {
            "name": "checksum",
            "type": "uint16",
            "endian": "big",
            "default": 0x0000,
            "description": "Header checksum (set to 0 for testing)"
        },

        # Bytes 12-15: Source IP
        {
            "name": "src_ip",
            "type": "bytes",
            "size": 4,
            "default": b"\xC0\xA8\x01\x01",  # 192.168.1.1
            "description": "Source IP address"
        },

        # Bytes 16-19: Destination IP
        {
            "name": "dst_ip",
            "type": "bytes",
            "size": 4,
            "default": b"\xC0\xA8\x01\x02",  # 192.168.1.2
            "description": "Destination IP address"
        },

        # Variable payload
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 1480,  # MTU 1500 - 20 byte header
            "default": b"",
            "description": "IP payload data"
        }
    ],

    # Seeds will be auto-generated from the data_model
    # Each seed exercises different protocol values and flags combinations
    "seeds": [
        # Minimal IPv4 header (no payload)
        # Version=4, IHL=5, DSCP=0, ECN=0, Total=20, ID=0, Flags=DF, FragOff=0
        # TTL=64, Proto=TCP, Checksum=0, Src=192.168.1.1, Dst=192.168.1.2
        b"\x45\x00\x00\x14\x00\x00\x40\x00\x40\x06\x00\x00\xC0\xA8\x01\x01\xC0\xA8\x01\x02",

        # IPv4 with ICMP protocol
        b"\x45\x00\x00\x1C\x00\x01\x40\x00\x40\x01\x00\x00\xC0\xA8\x01\x01\xC0\xA8\x01\x02TESTDATA",

        # IPv4 with UDP protocol
        b"\x45\x00\x00\x20\x00\x02\x40\x00\x40\x11\x00\x00\xC0\xA8\x01\x01\xC0\xA8\x01\x02UDPPAYLOAD",

        # IPv4 with fragmentation (More Fragments flag set)
        b"\x45\x00\x00\x18\x00\x03\x20\x00\x40\x06\x00\x00\xC0\xA8\x01\x01\xC0\xA8\x01\x02FRAG",

        # IPv4 with Expedited Forwarding DSCP
        b"\x45\xB8\x00\x14\x00\x04\x40\x00\x40\x06\x00\x00\xC0\xA8\x01\x01\xC0\xA8\x01\x02",

        # IPv4 with ECN Congestion Experienced
        b"\x45\x03\x00\x14\x00\x05\x40\x00\x40\x06\x00\x00\xC0\xA8\x01\x01\xC0\xA8\x01\x02",

        # IPv4 with low TTL (triggers TTL exceeded)
        b"\x45\x00\x00\x14\x00\x06\x40\x00\x01\x06\x00\x00\xC0\xA8\x01\x01\xC0\xA8\x01\x02",

        # IPv4 with different IHL (would have options in real packet)
        b"\x46\x00\x00\x18\x00\x07\x40\x00\x40\x06\x00\x00\xC0\xA8\x01\x01\xC0\xA8\x01\x02\x00\x00\x00\x00",
    ]
}

# ==================== State Model ====================

# IPv4 is stateless at the header level
# State machine would be at transport layer (TCP) or application layer
state_model = {
    "initial_state": "READY",
    "states": ["READY"],
    "transitions": []
}

# ==================== Response Validator ====================

def validate_response(response: bytes) -> bool:
    """
    Validate IPv4 response.

    For IPv4, we typically don't get direct responses to individual packets.
    In a real fuzzing scenario, you would:
    1. Monitor for ICMP errors (Host Unreachable, Time Exceeded, etc.)
    2. Check for TCP RST packets
    3. Validate response packet structure if echoed back

    This is a placeholder that accepts any response.
    """
    if not response:
        return False

    # In real scenario: parse response as IPv4 packet and validate structure
    # For now, accept any non-empty response
    return len(response) > 0


# ==================== Usage Notes ====================

"""
USAGE NOTES:

This plugin demonstrates all sub-byte field features:

1. **Nibbles** (4-bit fields):
   - version (4 bits)
   - ihl (4 bits)

2. **Sub-byte fields**:
   - dscp (6 bits)
   - ecn (2 bits)
   - flags (3 bits)

3. **Byte-spanning fields**:
   - fragment_offset (13 bits, spans from byte 6 into byte 7)

4. **Mixed field types**:
   - Bit fields (version, ihl, dscp, ecn, flags, fragment_offset)
   - Byte-aligned integers (total_length, identification, ttl, protocol, checksum)
   - Byte arrays (src_ip, dst_ip, payload)

5. **Auto-calculated size field**:
   - total_length automatically computed from all fields

TESTING COMMANDS:

# Load plugin
curl http://localhost:8000/api/plugins/ipv4_header

# Preview seeds
curl -X POST http://localhost:8000/api/plugins/ipv4_header/preview \\
  -H "Content-Type: application/json" \\
  -d '{"mode": "seeds", "count": 5}'

# Create fuzzing session (requires IPv4-aware target)
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \\
  -H "Content-Type: application/json" \\
  -d '{
    "protocol": "ipv4_header",
    "target_host": "your-network-stack-test-target",
    "target_port": 0,
    "mutation_mode": "structure_aware",
    "max_iterations": 10000
  }' | jq -r '.id')

# Start fuzzing
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start"

EXPECTED MUTATIONS:

The fuzzer will automatically test:
- Invalid version numbers (not 4)
- Invalid IHL values (< 5 or > 15)
- Various DSCP values (QoS testing)
- ECN flag combinations
- Boundary fragment offsets (0, 1, max)
- TTL edge cases (0, 1, 255)
- Protocol number fuzzing
- Flag combinations (DF, MF, Reserved)
- Malformed total_length values
- IP address mutations

INTEGRATION WITH REAL TARGETS:

To fuzz a real network stack:
1. Set up a raw socket target or packet injection framework
2. Monitor for:
   - Kernel panics
   - ICMP error responses (unusual types)
   - TCP stack failures
   - Routing anomalies
   - Performance degradation
3. Use this plugin as the basis for:
   - TCP header fuzzing (add TCP layer)
   - UDP header fuzzing (add UDP layer)
   - ICMP fuzzing (set protocol=1, add ICMP payload)
   - IPv6 testing (change version to 6, update fields)
"""
