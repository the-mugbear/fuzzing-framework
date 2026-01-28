"""
Transform Demo Protocol Plugin - Demonstrates Response Value Transformations

PURPOSE:
========
This plugin demonstrates the framework's ability to:
1. Copy values from server responses into subsequent client messages
2. Apply bitwise transformations to copied values
3. Chain multiple operations in a transformation pipeline

This addresses protocols where the client must:
- Receive a token/value from the server during connection setup
- Copy that value into future messages
- Derive other header fields through bit manipulation

EXAMPLE USE CASE:
=================
The server sends a 32-bit session token. The client must:
1. Echo the full token in future messages (session_token field)
2. Extract the 5 least significant bits, invert them, and place in header_check field

If server sends: 0x12345678
  - session_token = 0x12345678 (direct copy)
  - 5 LSBs of 0x12345678 = 0x18 (11000 binary)
  - Inverted 5 bits = 0x07 (00111 binary)
  - header_check = 0x07

TRANSFORMATION SYNTAX:
======================

Single operation:
    "field": {
        "copy_from_response": "source_field",
        "operation": "and_mask",
        "value": 0x1F
    }

Chained operations (pipeline):
    "field": {
        "copy_from_response": "source_field",
        "transform": [
            {"operation": "and_mask", "value": 0x1F},
            {"operation": "invert", "bit_width": 5},
        ]
    }

SUPPORTED OPERATIONS:
=====================
- add_constant: Add a constant value
- subtract_constant: Subtract a constant value
- xor_constant: XOR with a constant
- and_mask: Bitwise AND (extract bits)
- or_mask: Bitwise OR (set bits)
- shift_left: Left shift by N bits
- shift_right: Right shift by N bits
- invert: Bitwise NOT (with optional bit_width limit)
- modulo: Modulo operation

The 'invert' operation is special:
- Without bit_width: Inverts all bits (masked to 32 bits)
- With bit_width=N: Inverts only the N least significant bits
"""

__version__ = "1.0.0"
transport = "tcp"

# ==============================================================================
#  DATA MODEL - Client Request
# ==============================================================================

data_model = {
    "name": "TransformDemo",
    "description": "Demonstrates response value transformation capabilities",

    "blocks": [
        # =====================================================================
        # HEADER
        # =====================================================================
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"XFRM",
            "mutable": False,
        },
        {
            "name": "version",
            "type": "uint8",
            "default": 1,
            "mutable": False,
        },
        {
            "name": "message_type",
            "type": "uint8",
            "default": 0x01,  # INIT
            "values": {
                0x01: "INIT",
                0x02: "DATA",
                0x03: "CLOSE",
            },
        },

        # =====================================================================
        # DERIVED HEADER FIELDS
        # These fields are computed from the server's session token
        # =====================================================================
        {
            "name": "header_check",
            "type": "uint8",
            "default": 0,

            # HEADER CHECK FIELD:
            # This field must contain the 5 LSBs of the session token,
            # bitwise inverted. The server uses this to verify the client
            # correctly processed the token.
            #
            # Calculation:
            #   1. Take session_token from server response
            #   2. Extract 5 least significant bits (AND with 0x1F)
            #   3. Bitwise invert within 5-bit range
            #
            # Example:
            #   session_token = 0xABCD1234
            #   5 LSBs = 0x14 (10100 binary)
            #   Inverted = 0x0B (01011 binary)
            #   header_check = 0x0B
        },
        {
            "name": "header_xor",
            "type": "uint8",
            "default": 0,

            # HEADER XOR FIELD:
            # Another derived field - XOR of upper and lower bytes of token.
            # Demonstrates multi-step transformation:
            #   1. Extract bits 8-15 (second byte)
            #   2. XOR with bits 0-7 (first byte)
        },

        # =====================================================================
        # SESSION FIELDS
        # =====================================================================
        {
            "name": "session_token",
            "type": "uint32",
            "endian": "big",
            "default": 0,

            # SESSION TOKEN:
            # Copied directly from server's INIT response.
            # Must be included in all subsequent messages.
        },
        {
            "name": "sequence",
            "type": "uint16",
            "endian": "big",
            "default": 0,
            "behavior": {
                "operation": "increment",
                "initial": 0,
                "step": 1,
            },
        },

        # =====================================================================
        # PAYLOAD
        # =====================================================================
        {
            "name": "payload_len",
            "type": "uint16",
            "endian": "big",
            "is_size_field": True,
            "size_of": "payload",
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 1024,
            "default": b"",
        },
    ],

    "seeds": [
        # Seed 1: INIT message (session_token=0, server will assign)
        (
            b"XFRM"                   # magic
            b"\x01"                   # version
            b"\x01"                   # message_type = INIT
            b"\x00"                   # header_check (will be set by response handler)
            b"\x00"                   # header_xor (will be set by response handler)
            b"\x00\x00\x00\x00"       # session_token (will be set by response handler)
            b"\x00\x00"               # sequence
            b"\x00\x00"               # payload_len
        ),

        # Seed 2: DATA message template
        (
            b"XFRM"
            b"\x01"
            b"\x02"                   # message_type = DATA
            b"\x00"                   # header_check
            b"\x00"                   # header_xor
            b"\x00\x00\x00\x00"       # session_token
            b"\x00\x01"               # sequence = 1
            b"\x00\x05"               # payload_len = 5
            b"Hello"                  # payload
        ),
    ],
}

# ==============================================================================
#  RESPONSE MODEL - Server Response
# ==============================================================================

response_model = {
    "name": "TransformDemoResponse",

    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"XFRM",
        },
        {
            "name": "version",
            "type": "uint8",
            "default": 1,
        },
        {
            "name": "status",
            "type": "uint8",
            "default": 0x00,
            "values": {
                0x00: "OK",
                0x01: "ERROR",
                0x02: "INVALID_CHECK",
            },
        },
        {
            "name": "session_token",
            "type": "uint32",
            "endian": "big",
            "default": 0,

            # SESSION TOKEN:
            # Server-assigned token that client must copy and use
            # to derive header_check field.
        },
        {
            "name": "server_sequence",
            "type": "uint16",
            "endian": "big",
            "default": 0,
        },
    ],
}

# ==============================================================================
#  RESPONSE HANDLERS - The Key Feature Demonstration
# ==============================================================================

response_handlers = [
    {
        # Handler 1: Process successful INIT response
        # This demonstrates the transformation pipeline
        "name": "process_init_response",

        # Match on successful status
        "match": {
            "status": 0x00,
        },

        "set_fields": {
            # Change message type from INIT to DATA for subsequent messages
            "message_type": 0x02,  # DATA

            # DIRECT COPY: Copy session_token as-is
            "session_token": {
                "copy_from_response": "session_token",
            },

            # TRANSFORMATION PIPELINE: Extract 5 LSBs and invert
            # This is the key demonstration of the new feature!
            #
            # Step-by-step for session_token = 0xABCD1234:
            #   1. and_mask 0x1F: 0x1234 & 0x1F = 0x14 (10100)
            #   2. invert 5 bits: ~0x14 & 0x1F = 0x0B (01011)
            "header_check": {
                "copy_from_response": "session_token",
                "transform": [
                    {"operation": "and_mask", "value": 0x1F},      # Extract 5 LSBs
                    {"operation": "invert", "bit_width": 5},       # Invert within 5 bits
                ],
            },

            # COMPLEX TRANSFORMATION: XOR of bytes 1 and 0
            # Demonstrates shift and XOR operations
            #
            # For session_token = 0xABCD1234:
            #   1. Copy value: 0xABCD1234
            #   2. Shift right 8: 0x00ABCD12
            #   3. XOR with original & 0xFF: 0x12 ^ 0x34 = 0x26
            #
            # Note: This requires two separate extractions combined,
            # which isn't directly supported. Instead, we demonstrate
            # a simpler XOR with constant:
            "header_xor": {
                "copy_from_response": "session_token",
                "transform": [
                    {"operation": "and_mask", "value": 0xFF},      # Get byte 0
                    {"operation": "xor_constant", "value": 0xAA},  # XOR with constant
                ],
            },
        },
    },

    {
        # Handler 2: Handle INVALID_CHECK error by resetting
        "name": "handle_invalid_check",
        "match": {
            "status": 0x02,  # INVALID_CHECK
        },
        "set_fields": {
            # Reset to INIT to re-establish session
            "message_type": 0x01,
            "session_token": 0,
            "header_check": 0,
            "header_xor": 0,
        },
    },
]

# ==============================================================================
#  STATE MODEL
# ==============================================================================

state_model = {
    "initial_state": "DISCONNECTED",
    "states": ["DISCONNECTED", "INIT_SENT", "ESTABLISHED"],
    "transitions": [
        {
            "from": "DISCONNECTED",
            "to": "INIT_SENT",
            "message_type": "INIT",
        },
        {
            "from": "INIT_SENT",
            "to": "ESTABLISHED",
            "message_type": "DATA",
        },
        {
            "from": "ESTABLISHED",
            "to": "ESTABLISHED",
            "message_type": "DATA",
        },
        {
            "from": "ESTABLISHED",
            "to": "DISCONNECTED",
            "message_type": "CLOSE",
        },
    ],
}

# ==============================================================================
#  RESPONSE VALIDATOR
# ==============================================================================

def validate_response(response: bytes) -> bool:
    """Validate server response."""
    if len(response) < 10:
        return False

    # Check magic
    if response[:4] != b"XFRM":
        return False

    # Check status is valid
    status = response[5]
    if status > 0x02:
        return False

    return True
