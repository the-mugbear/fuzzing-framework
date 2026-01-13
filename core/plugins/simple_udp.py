"""
Simple UDP protocol plugin.

- Purpose: Minimal datagram protocol for UDP transport testing.
- Transport: UDP.
- Includes: Magic header, sequence, command, and optional payload.
"""

__version__ = "1.0.0"
transport = "udp"

data_model = {
    "name": "SimpleUDP",
    "description": "Minimal UDP datagram protocol",
    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"SUDP",
            "mutable": False,
        },
        {
            "name": "sequence",
            "type": "uint16",
            "endian": "big",
            "default": 0,
        },
        {
            "name": "command",
            "type": "uint8",
            "values": {
                0x01: "PING",
                0x02: "DATA",
                0x03: "RESET",
            },
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 64,
            "default": b"",
        },
    ],
    "seeds": [
        b"SUDP\x00\x01\x01",  # PING
        b"SUDP\x00\x05\x02hello",  # DATA
        b"SUDP\x00\x00\x03",  # RESET
    ],
}

state_model = {
    "initial_state": "READY",
    "states": ["READY", "STREAMING"],
    "transitions": [
        {"from": "READY", "to": "READY", "trigger": "ping", "message_type": "PING"},
        {"from": "READY", "to": "STREAMING", "trigger": "send_data", "message_type": "DATA"},
        {"from": "STREAMING", "to": "READY", "trigger": "reset", "message_type": "RESET"},
    ],
}


def validate_response(response: bytes) -> bool:
    """Simple sanity check for UDP echo responses."""
    if len(response) < 5:
        return False
    if not response.startswith(b"SUDP"):
        return False
    # ensure command byte isn't the reserved error opcode
    return response[5] != 0xFF
