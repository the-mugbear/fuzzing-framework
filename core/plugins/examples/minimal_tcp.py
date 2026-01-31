"""
Minimal TCP Protocol Example - START HERE

This is the simplest possible protocol plugin. Use this as your starting
template when building a new custom protocol.

Features demonstrated:
- Magic header (immutable bytes field)
- Length-prefixed payload (is_size_field + size_of)
- Command codes with values enum
- Simple state machine (INIT → AUTH → READY → CLOSED)
- Validation oracle (validate_response function)
- Manual seed corpus

Test server: tests/simple_tcp_server.py
"""

__version__ = "1.0.0"
transport = "tcp"

# Data model defines message structure
data_model = {
    "name": "SimpleTCP",
    "description": "A simple TCP protocol for testing",
    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"STCP",
            "mutable": False,  # Don't mutate magic header
        },
        {
            "name": "length",
            "type": "uint32",
            "endian": "big",
            "is_size_field": True,
            "size_of": "payload",
        },
        {
            "name": "command",
            "type": "uint8",
            "values": {
                0x01: "AUTH",
                0x02: "DATA",
                0x03: "QUIT",
                0xFF: "ERROR",
            },
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 1024,
            "default": b"",
        },
    ],
    # Seed corpus (base test cases)
    # NOTE: Seeds are now OPTIONAL! If omitted, they will be auto-generated
    # from the data_model blocks above. Manual seeds are still supported for
    # custom test cases or specific edge cases.
    "seeds": [
        b"STCP\x00\x00\x00\x05\x01HELLO",  # AUTH - manual seed example
        b"STCP\x00\x00\x00\x04\x02TEST",  # DATA - manual seed example
        b"STCP\x00\x00\x00\x00\x03",  # QUIT - manual seed example
    ],
    # To use auto-generated seeds only, simply omit the "seeds" key or set it to []
}

# State model defines protocol state machine
state_model = {
    "initial_state": "INIT",
    "states": ["INIT", "AUTH", "READY", "CLOSED"],
    "transitions": [
        {
            "from": "INIT",
            "to": "AUTH",
            "trigger": "send_auth",
            "message_type": "AUTH",
            "expected_response": "AUTH_OK",
        },
        {
            "from": "AUTH",
            "to": "READY",
            "trigger": "auth_success",
            "expected_response": "READY",
        },
        {
            "from": "READY",
            "to": "READY",
            "trigger": "send_data",
            "message_type": "DATA",
        },
        {
            "from": "READY",
            "to": "CLOSED",
            "trigger": "send_quit",
            "message_type": "QUIT",
        },
    ],
}


def validate_response(response: bytes) -> bool:
    """
    Optional validation function for response checking

    This is the "Specification Oracle" - allows domain experts
    to define application-specific correctness checks.

    Args:
        response: Raw response bytes from target

    Returns:
        True if response is valid, False or raises exception if invalid

    Raises:
        ValueError: On logical errors (e.g., negative balance)
    """
    if len(response) < 4:
        return False

    # Check magic header
    if response[:4] != b"STCP":
        return False

    # Example: Check for error responses that shouldn't happen
    if len(response) > 8 and response[8] == 0xFF:
        # This would be a logical failure
        return False

    return True
