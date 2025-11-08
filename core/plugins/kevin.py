"""
My Custom Protocol Plugin
Implements fuzzing for MyProtocol v1.0
"""

__version__ = "1.0.0"

# Required: Data Model
data_model = {
    "name": "KMcMurdieTestProtocol",
    "description": "Stateful test protocol for demonstration purposes",

    # Define message structure as blocks
    "blocks": [
        {
            "name": "magic",           # Field identifier
            "type": "bytes",           # Data type
            "size": 4,                 # Fixed size in bytes
            "default": b"KEVN",        # Default value
            "mutable": False           # Don't mutate (for magic headers) MUTABLE DEFAULTS TO TRUE
        },
        {
            "name": "length",
            "type": "uint32",          # 32-bit unsigned integer
            "endian": "big",           # big or little endian
            "is_size_field": True,     # This field indicates data size
            "size_of": "payload"       # References another field
        },
        {
            "name": "command",
            "type": "uint8",           # 8-bit unsigned integer
            "values": {                # Known command codes
                0x01: "CONNECT",
                0x02: "DATA",
                0x03: "DISCONNECT"
            }
        },
        {
            "name": "sequenceNumber",
            "type": "bytes",
            "max_size": 8,          # Maximum size for mutation
            "default": b"0x0"
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 1024,          # Maximum size for mutation
            "default": b""
        }
    ],

    # Seed corpus: example messages for fuzzing
    "seeds": [
        b"KEVN\x00\x00\x00\x05\x01HELLO",
        b"KEVN\x00\x00\x00\x04\x02DATA",
        b"KEVN\x00\x00\x00\x00\x03"
    ]
}

# Required: State Model
state_model = {
    "initial_state": "INIT",

    # Define protocol states
    "states": ["INIT", "CONNECTED", "AUTHENTICATED", "CLOSED"],

    # Define state transitions
    "transitions": [
        {
            "from": "INIT",
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
            "to": "AUTHENTICATED",
            "trigger": "data_exchange",
            "message_type": "DATA"
        },
        {
            "from": "AUTHENTICATED",
            "to": "CLOSED",
            "trigger": "disconnect",
            "message_type": "DISCONNECT"
        }
    ]
}

# Optional: Custom Response Validator
def validate_response(response: bytes) -> bool:
    """
    Application-specific response validation.

    This is your "Specification Oracle" - check for logical
    errors that wouldn't cause a crash but violate protocol rules.

    Args:
        response: Raw response bytes from target

    Returns:
        True if response is valid, False if logical error detected

    Raises:
        ValueError: To flag as logical failure with description
    """
    if len(response) < 4:
        return False

    # Verify magic header
    if response[:4] != b"MYPK":
        return False

    # Example: Check for application-specific errors
    if len(response) > 8:
        command = response[8]

        # Error response should never happen in normal flow
        if command == 0xFF:
            return False

        # Check for impossible states
        # Example: Balance should never be negative in financial protocol
        # if response_type == "BALANCE" and parse_balance(response) < 0:
        #     raise ValueError("Negative balance detected - logic bug!")

    return True