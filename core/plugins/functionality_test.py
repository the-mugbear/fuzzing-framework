"""
Functionality test protocol plugin.

- Purpose: End-to-end validation for core fuzzer workflows.
- Transport: TCP.
- Pairs with: tests/functionality_server.py.
- Includes: Seeds, behaviors, response handlers, and validation examples.
"""

from typing import Callable

transport = "tcp"
__version__ = "1.0.0"

# Data Model (fields are intentionally simple and observable)
data_model = {
    "name": "FunctionalityTest",
    "description": "Simple request/response protocol for exercising the fuzzer stack",
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"FTST", "mutable": False},
        {
            "name": "sequence",
            "type": "uint16",
            "behavior": {"operation": "increment", "initial": 0, "step": 1},
        },
        {
            "name": "opcode",
            "type": "uint8",
            "values": {
                0x01: "PING",
                0x02: "ECHO",
                0x03: "FAIL",
                0x04: "CLOSE",
                0x81: "PONG",
                0x82: "ECHO_RESP",
                0xFF: "ERROR",
            },
        },
        {
            "name": "length",
            "type": "uint16",
            "endian": "big",
            "is_size_field": True,
            "size_of": "payload",
        },
        {"name": "payload", "type": "bytes", "max_size": 256, "default": b""},
    ],
    "seeds": [
        b"FTST\x00\x00\x01\x00\x00",  # PING, empty payload
        b"FTST\x00\x00\x02\x00\x05hello",  # ECHO "hello"
    ],
}

# Stateless response layout mirrors requests
response_model = data_model

# State Model
state_model = {
    "initial_state": "INIT",
    "states": ["INIT", "OPEN", "ERROR", "CLOSED"],
    "transitions": [
        {"from": "INIT", "to": "OPEN", "message_type": "PING", "expected_response": "PONG"},
        {"from": "OPEN", "to": "OPEN", "message_type": "ECHO", "expected_response": "ECHO_RESP"},
        {"from": "OPEN", "to": "ERROR", "message_type": "FAIL", "expected_response": "ERROR"},
        {"from": "OPEN", "to": "CLOSED", "message_type": "CLOSE"},
    ],
}


def validate_response(response: bytes) -> bool:
    """Basic oracle to reject malformed responses."""
    if len(response) < 9:
        return False
    if response[:4] != b"FTST":
        return False

    seq = int.from_bytes(response[4:6], "big")
    opcode = response[6]
    length = int.from_bytes(response[7:9], "big")
    if length != len(response) - 9:
        return False
    if length > 256:
        return False

    valid_opcodes = {0x81, 0x82, 0xFF, 0x04}
    if opcode not in valid_opcodes:
        return False

    # Responses should carry payload for ECHO_RESP and ERROR
    if opcode in (0x82, 0xFF) and length == 0:
        return False

    # Simple monotonic check: sequence should fit in 16 bits
    return 0 <= seq <= 0xFFFF


# Response handlers to sync sequence numbers and payload echoes in agent mode
def _copy_sequence(parsed_response):
    return parsed_response.get("sequence")


response_handlers = [
    {
        "name": "sync_pong",
        "match": {"opcode": 0x81},
        "set_fields": {"opcode": 0x01, "sequence": {"copy_from_response": "sequence"}},
    },
    {
        "name": "echo_followup",
        "match": {"opcode": 0x82},
        "set_fields": {
            "opcode": 0x02,
            "payload": {"copy_from_response": "payload"},
            "sequence": {"copy_from_response": "sequence"},
        },
    },
]
