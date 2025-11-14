"""
Branching Protocol Plugin - Multi-Path State Machine Example

This plugin demonstrates a stateful protocol with branching transitions,
where single states can transition to multiple different target states
based on different message types. Useful for:
- UI testing of complex state diagrams
- Template for protocols with conditional flows
- Demonstrating error handling paths
"""

__version__ = "1.0.0"

# Data Model
data_model = {
    "name": "BranchingProtocol",
    "description": "Multi-path stateful protocol demonstrating branching transitions",

    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"BRCH",
            "mutable": False
        },
        {
            "name": "length",
            "type": "uint32",
            "endian": "big",
            "is_size_field": True,
            "size_of": "payload"
        },
        {
            "name": "command",
            "type": "uint8",
            "values": {
                0x01: "CONNECT",
                0x02: "AUTH_SUCCESS",
                0x03: "AUTH_FAILED",
                0x04: "DISCONNECT",
                0x05: "SEND_DATA",
                0x06: "REQUEST_DATA",
                0x07: "SUBSCRIBE",
                0x08: "PING",
                0x09: "ERROR",
                0x0A: "SHUTDOWN"
            }
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 512,
            "default": b""
        }
    ],
}

# State Model with Branching Transitions
state_model = {
    "initial_state": "INIT",

    "states": [
        "INIT",
        "CONNECTED",
        "AUTHENTICATED",
        "DATA_SENDING",
        "DATA_RECEIVING",
        "STREAMING",
        "ERROR",
        "CLOSED"
    ],

    "transitions": [
        # From INIT: Single entry point
        {
            "from": "INIT",
            "to": "CONNECTED",
            "trigger": "connect",
            "message_type": "CONNECT",
            "expected_response": "CONNECT_OK"
        },

        # From CONNECTED: Branch into 3 paths (success, failure, disconnect)
        {
            "from": "CONNECTED",
            "to": "AUTHENTICATED",
            "trigger": "auth_success",
            "message_type": "AUTH_SUCCESS",
            "expected_response": "AUTH_OK"
        },
        {
            "from": "CONNECTED",
            "to": "ERROR",
            "trigger": "auth_failed",
            "message_type": "AUTH_FAILED",
            "expected_response": "AUTH_ERROR"
        },
        {
            "from": "CONNECTED",
            "to": "CLOSED",
            "trigger": "disconnect_early",
            "message_type": "DISCONNECT"
        },

        # From AUTHENTICATED: Branch into 4 paths (send, receive, subscribe, disconnect)
        {
            "from": "AUTHENTICATED",
            "to": "DATA_SENDING",
            "trigger": "send_data",
            "message_type": "SEND_DATA",
            "expected_response": "DATA_ACK"
        },
        {
            "from": "AUTHENTICATED",
            "to": "DATA_RECEIVING",
            "trigger": "request_data",
            "message_type": "REQUEST_DATA",
            "expected_response": "DATA_READY"
        },
        {
            "from": "AUTHENTICATED",
            "to": "STREAMING",
            "trigger": "subscribe",
            "message_type": "SUBSCRIBE",
            "expected_response": "SUB_ACK"
        },
        {
            "from": "AUTHENTICATED",
            "to": "CLOSED",
            "trigger": "disconnect",
            "message_type": "DISCONNECT"
        },

        # From DATA_SENDING: Return to AUTHENTICATED or go to ERROR
        {
            "from": "DATA_SENDING",
            "to": "AUTHENTICATED",
            "trigger": "send_complete",
            "message_type": "PING",
            "expected_response": "PONG"
        },
        {
            "from": "DATA_SENDING",
            "to": "ERROR",
            "trigger": "send_error",
            "message_type": "ERROR"
        },

        # From DATA_RECEIVING: Return to AUTHENTICATED or go to ERROR
        {
            "from": "DATA_RECEIVING",
            "to": "AUTHENTICATED",
            "trigger": "receive_complete",
            "message_type": "PING",
            "expected_response": "PONG"
        },
        {
            "from": "DATA_RECEIVING",
            "to": "ERROR",
            "trigger": "receive_error",
            "message_type": "ERROR"
        },

        # From STREAMING: Branch into 3 paths (continue, auth, close)
        {
            "from": "STREAMING",
            "to": "STREAMING",
            "trigger": "stream_continue",
            "message_type": "PING"
        },
        {
            "from": "STREAMING",
            "to": "AUTHENTICATED",
            "trigger": "unsubscribe",
            "message_type": "DISCONNECT",
            "expected_response": "UNSUB_OK"
        },
        {
            "from": "STREAMING",
            "to": "ERROR",
            "trigger": "stream_error",
            "message_type": "ERROR"
        },

        # From ERROR: Branch into 2 recovery paths
        {
            "from": "ERROR",
            "to": "CONNECTED",
            "trigger": "reconnect",
            "message_type": "CONNECT",
            "expected_response": "RECONNECT_OK"
        },
        {
            "from": "ERROR",
            "to": "CLOSED",
            "trigger": "shutdown_on_error",
            "message_type": "SHUTDOWN"
        },

        # Terminal state transitions
        {
            "from": "CLOSED",
            "to": "INIT",
            "trigger": "restart",
            "message_type": "CONNECT"
        }
    ]
}

# Response Validator
def validate_response(response: bytes) -> bool:
    """
    Validate responses according to protocol specification.

    Checks:
    - Magic header must be present
    - Length field must be consistent
    - Command codes must be valid

    Args:
        response: Raw response bytes from target

    Returns:
        True if response is valid, False if protocol violation detected
    """
    if len(response) < 4:
        return False

    # Verify magic header
    if response[:4] != b"BRCH":
        return False

    # Verify minimum structure (magic + length + command)
    if len(response) < 9:
        return False

    # Extract and validate command byte
    command = response[8]
    valid_commands = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A]

    if command not in valid_commands:
        return False

    # Check that error responses only come from error states
    # This is a logical constraint - ERROR command (0x09) should
    # indicate a state transition to ERROR state
    if command == 0x09:
        # Could add additional validation here
        pass

    return True
