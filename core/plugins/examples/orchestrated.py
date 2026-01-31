"""
Orchestrated Protocol Example - Multi-Stage Authentication

This plugin demonstrates orchestration features for protocols that require
authentication or handshaking before fuzzing can begin.

Use this as a template when your protocol has:
- Login/authentication phase before normal operation
- Session tokens that must be extracted and reused
- Heartbeat/keepalive requirements
- Graceful logout/teardown

Features demonstrated:
- protocol_stack: Define bootstrap → fuzz_target → teardown stages
- from_context: Inject values extracted from earlier stages
- exports: Extract values from responses (session tokens, intervals)
- heartbeat: Periodic keepalive with context-based interval
- connection: Session-level persistent connections

Protocol Flow:
1. AUTH stage (bootstrap): Send credentials, receive session token
2. APPLICATION stage (fuzz_target): Fuzz with token injected
3. LOGOUT stage (teardown): Clean session teardown
"""

__version__ = "1.0.0"
__author__ = "Fuzzing Framework"

# Protocol stack defines the execution order
protocol_stack = [
    {
        "name": "auth",
        "role": "bootstrap",
        "data_model": {
            "name": "AuthRequest",
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4, "default": b"ORCH", "mutable": False},
                {"name": "msg_type", "type": "uint8", "default": 0x01, "mutable": False},
                {"name": "length", "type": "uint16", "endian": "big", "is_size_field": True, "size_of": "credentials"},
                {"name": "credentials", "type": "bytes", "max_size": 64, "default": b"user:pass"},
            ],
        },
        "response_model": {
            "name": "AuthResponse",
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4},
                {"name": "msg_type", "type": "uint8"},
                {"name": "length", "type": "uint16", "endian": "big"},
                {"name": "status", "type": "uint8"},  # 0x00 = success
                {"name": "session_token", "type": "uint32", "endian": "big"},
                {"name": "heartbeat_interval", "type": "uint16", "endian": "big"},  # ms
            ],
        },
        "expect": {
            "status": 0x00,  # Require success status
        },
        "exports": {
            # Extract values from response and store in context
            "session_token": {"from": "session_token"},
            "hb_interval": {"from": "heartbeat_interval"},
        },
        "retry": {
            "max_attempts": 3,
            "delay_ms": 1000,
        },
    },
    {
        "name": "application",
        "role": "fuzz_target",
        "data_model": {
            "name": "DataRequest",
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4, "default": b"ORCH", "mutable": False},
                {"name": "msg_type", "type": "uint8", "default": 0x10, "mutable": False},
                {"name": "length", "type": "uint16", "endian": "big", "is_size_field": True, "size_of": "payload"},
                # Token is injected from context (extracted during auth stage)
                {"name": "token", "type": "uint32", "endian": "big", "from_context": "session_token"},
                {"name": "sequence", "type": "uint32", "endian": "big", "generate": "sequence"},
                {"name": "payload", "type": "bytes", "max_size": 1024, "default": b"PING"},
            ],
        },
        "response_model": {
            "name": "DataResponse",
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4},
                {"name": "msg_type", "type": "uint8"},
                {"name": "length", "type": "uint16", "endian": "big"},
                {"name": "status", "type": "uint8"},
                {"name": "echo_seq", "type": "uint32", "endian": "big"},
                {"name": "response_data", "type": "bytes", "max_size": 1024},
            ],
        },
    },
    {
        "name": "logout",
        "role": "teardown",
        "data_model": {
            "name": "LogoutRequest",
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4, "default": b"ORCH", "mutable": False},
                {"name": "msg_type", "type": "uint8", "default": 0xFF, "mutable": False},
                {"name": "length", "type": "uint16", "endian": "big", "default": 4},
                {"name": "token", "type": "uint32", "endian": "big", "from_context": "session_token"},
            ],
        },
    },
]

# Heartbeat configuration - uses context value for interval
heartbeat = {
    "enabled": True,
    "interval_ms": {"from_context": "hb_interval"},  # Use value from auth response
    "jitter_ms": 100,
    "message": {
        "data_model": {
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4, "default": b"ORCH"},
                {"name": "msg_type", "type": "uint8", "default": 0x20},
                {"name": "length", "type": "uint16", "endian": "big", "default": 4},
                {"name": "token", "type": "uint32", "endian": "big", "from_context": "session_token"},
            ],
        },
    },
    "expect_response": True,
    "expected_response": b"ORCH\x21",  # Expect HEARTBEAT_ACK
    "on_timeout": {
        "action": "reconnect",
        "max_failures": 3,
        "rebootstrap": True,  # Re-run auth stage on reconnect
    },
}

# Connection lifecycle configuration
connection = {
    "mode": "session",  # Keep connection alive for entire session
    "idle_timeout_ms": 30000,
    "max_reconnects": 5,
}

# Main data model (for backwards compatibility with simple protocols)
# This is also the fuzz_target stage's data model
data_model = protocol_stack[1]["data_model"]

# State model for stateful fuzzing
state_model = {
    "initial_state": "UNAUTHENTICATED",
    "states": ["UNAUTHENTICATED", "AUTHENTICATED", "READY", "ERROR"],
    "transitions": [
        {
            "from": "UNAUTHENTICATED",
            "to": "AUTHENTICATED",
            "message": "auth",
            "response_check": {"status": 0x00},
        },
        {
            "from": "AUTHENTICATED",
            "to": "READY",
            "message": "application",
            "response_check": {"status": 0x00},
        },
        {
            "from": "READY",
            "to": "READY",
            "message": "application",
        },
        {
            "from": "*",
            "to": "UNAUTHENTICATED",
            "message": "logout",
        },
        {
            "from": "*",
            "to": "ERROR",
            "message": "*",
            "response_check": {"status": {"not": 0x00}},
        },
    ],
}


def validate_response(response: bytes) -> bool:
    """
    Specification oracle - validates response format and content.

    Returns True if response is valid, False for logical failures.
    """
    if len(response) < 7:
        return False  # Too short

    magic = response[:4]
    if magic != b"ORCH":
        return False  # Invalid magic

    msg_type = response[4]
    length = int.from_bytes(response[5:7], "big")

    # Verify length matches actual payload
    expected_len = 7 + length  # header + payload
    if len(response) < expected_len:
        return False  # Truncated response

    # Response types should be odd (0x02, 0x11, 0x21)
    if msg_type not in (0x02, 0x11, 0x21):
        return False  # Unknown response type

    return True


# Seeds for initial corpus
seeds = [
    # Basic authenticated data request
    b"ORCH\x10\x00\x08\x00\x00\x00\x01\x00\x00\x00\x01PING",
    # Data request with longer payload
    b"ORCH\x10\x00\x10\x00\x00\x00\x01\x00\x00\x00\x02TESTDATA1234",
]
