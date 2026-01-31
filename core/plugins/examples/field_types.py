"""
Field Types Quick Reference - Copy-Paste Examples

This plugin provides concise, copy-paste ready examples of ALL field types
and operations. Use this when you need to quickly look up the syntax for
a specific field type or operation.

For comprehensive tutorial documentation, see feature_reference.py.
For minimal starting templates, see minimal_tcp.py or minimal_udp.py.

TABLE OF CONTENTS:
==================
1. FIELD TYPES (lines 40-120)
   - Integer types: uint8, uint16, uint32, uint64, int8, int16, int32, int64
   - Byte arrays: fixed size, variable size with max_size
   - Bit fields: sub-byte fields packed MSB-first
   - Strings: with encoding

2. FIELD ATTRIBUTES (lines 125-180)
   - default: Initial value
   - mutable: False prevents fuzzer mutations
   - endian: "big" or "little" byte order
   - values: Document valid enum values
   - is_size_field/size_of: Link length field to data field

3. BEHAVIORS (lines 185-230)
   - increment: Auto-incrementing sequence numbers
   - add_constant: Add value on each send

4. RESPONSE HANDLERS (lines 235-350)
   - match: Condition for handler activation
   - set_fields: Static values or copy_from_response
   - extract_bits: Extract specific bit ranges
   - transform: Chained operations pipeline

5. TRANSFORM OPERATIONS (lines 355-420)
   - Arithmetic: add_constant, subtract_constant, modulo
   - Bitwise: and_mask, or_mask, xor_constant, invert, shift_left, shift_right

6. STATE MODEL (lines 425-460)
   - States and transitions for stateful protocols
"""

__version__ = "1.0.0"
transport = "tcp"

# ==============================================================================
#  SECTION 1: FIELD TYPES
# ==============================================================================

data_model = {
    "name": "FieldOperationsReference",
    "description": "Reference examples for all supported field operations",

    "blocks": [
        # ----------------------------------------------------------------------
        # INTEGER TYPES - Unsigned
        # ----------------------------------------------------------------------
        {
            "name": "uint8_example",
            "type": "uint8",
            "default": 0x01,
        },
        {
            "name": "uint16_example",
            "type": "uint16",
            "endian": "big",  # Network byte order (default)
            "default": 0x0102,
        },
        {
            "name": "uint32_example",
            "type": "uint32",
            "endian": "little",  # Intel byte order
            "default": 0x01020304,
        },
        # uint64 also supported: "type": "uint64"

        # ----------------------------------------------------------------------
        # INTEGER TYPES - Signed
        # ----------------------------------------------------------------------
        {
            "name": "int16_example",
            "type": "int16",
            "endian": "big",
            "default": -1,  # Stored as 0xFFFF
        },
        # int8, int32, int64 also supported

        # ----------------------------------------------------------------------
        # BIT FIELDS - Sub-byte fields packed MSB-first
        # ----------------------------------------------------------------------
        # These 8 bits pack into 1 byte: [version:4][flags:4]
        {
            "name": "version_bits",
            "type": "bits",
            "size": 4,  # 4 bits (0-15)
            "default": 1,
        },
        {
            "name": "flag_bits",
            "type": "bits",
            "size": 4,  # 4 bits
            "default": 0,
            "values": {  # Document bit meanings
                0x01: "FLAG_A",
                0x02: "FLAG_B",
                0x04: "FLAG_C",
                0x08: "FLAG_D",
            },
        },

        # ----------------------------------------------------------------------
        # BYTE ARRAYS - Fixed and Variable Size
        # ----------------------------------------------------------------------
        {
            "name": "magic_header",
            "type": "bytes",
            "size": 4,  # Fixed 4 bytes
            "default": b"REF!",
            "mutable": False,  # Don't fuzz protocol magic
        },
        {
            "name": "payload_length",
            "type": "uint16",
            "endian": "big",
            "is_size_field": True,  # This field contains a length
            "size_of": "payload",   # ...of this field
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 256,  # Variable length, up to 256 bytes
            "default": b"",
        },

        # ----------------------------------------------------------------------
        # STRING FIELDS
        # ----------------------------------------------------------------------
        {
            "name": "string_field",
            "type": "string",
            "max_size": 32,
            "encoding": "utf-8",  # Also: "ascii", "latin-1"
            "default": "",
        },

        # ==============================================================================
        #  SECTION 2: FIELD ATTRIBUTES
        # ==============================================================================

        # ----------------------------------------------------------------------
        # VALUES - Document Valid Enum Values
        # ----------------------------------------------------------------------
        {
            "name": "command_code",
            "type": "uint8",
            "default": 0x01,
            "values": {
                0x01: "INIT",
                0x02: "DATA",
                0x03: "ACK",
                0x04: "CLOSE",
                0xFF: "ERROR",
            },
        },

        # ==============================================================================
        #  SECTION 3: BEHAVIORS - Auto-Updated Fields
        # ==============================================================================

        # ----------------------------------------------------------------------
        # INCREMENT - Auto-incrementing sequence numbers
        # ----------------------------------------------------------------------
        {
            "name": "sequence_number",
            "type": "uint16",
            "endian": "big",
            "default": 0,
            "behavior": {
                "operation": "increment",
                "initial": 0,      # Starting value
                "step": 1,         # Increment by 1
                "wrap": 0x10000,   # Wrap at 65536 (back to 0)
            },
        },

        # ----------------------------------------------------------------------
        # ADD_CONSTANT - Add fixed value on each send
        # ----------------------------------------------------------------------
        {
            "name": "counter_field",
            "type": "uint8",
            "default": 0,
            "behavior": {
                "operation": "add_constant",
                "value": 5,  # Add 5 to current value
            },
        },

        # ----------------------------------------------------------------------
        # FIELDS FOR RESPONSE HANDLER DEMOS
        # ----------------------------------------------------------------------
        {
            "name": "session_token",
            "type": "uint32",
            "endian": "big",
            "default": 0,
            # Will be populated by response handler
        },
        {
            "name": "derived_check",
            "type": "uint8",
            "default": 0,
            # Will be computed from session_token
        },
    ],

    # ==========================================================================
    # SEEDS - Example Messages
    # ==========================================================================
    "seeds": [
        (
            b"REF!"           # magic_header (4 bytes)
            b"\x01"           # uint8_example
            b"\x01\x02"       # uint16_example (big endian)
            b"\x04\x03\x02\x01"  # uint32_example (little endian)
            b"\xff\xff"       # int16_example (-1)
            b"\x10"           # version_bits:4 + flag_bits:4 = 0x10
            b"\x00\x04"       # payload_length
            b"test"           # payload
            b"\x00"           # string_field (empty, null terminated)
            b"\x01"           # command_code
            b"\x00\x00"       # sequence_number
            b"\x00"           # counter_field
            b"\x00\x00\x00\x00"  # session_token
            b"\x00"           # derived_check
        ),
    ],
}


# ==============================================================================
#  SECTION 4: RESPONSE MODEL - Server Response Structure
# ==============================================================================

response_model = {
    "name": "ReferenceResponse",

    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
        },
        {
            "name": "status",
            "type": "uint8",
            "values": {
                0x00: "OK",
                0x01: "ERROR",
            },
        },
        {
            "name": "server_token",
            "type": "uint32",
            "endian": "big",
        },
        {
            "name": "server_flags",
            "type": "uint16",
            "endian": "big",
        },
    ],
}


# ==============================================================================
#  SECTION 5: RESPONSE HANDLERS - All Copy/Transform Examples
# ==============================================================================

response_handlers = [
    # --------------------------------------------------------------------------
    # SIMPLE COPY - Copy value from response to request field
    # --------------------------------------------------------------------------
    {
        "name": "copy_token_simple",
        "match": {"status": 0x00},  # Only on success
        "set_fields": {
            # Static value assignment
            "command_code": 0x02,

            # Copy from response (most common pattern)
            "session_token": {
                "copy_from_response": "server_token",
            },
        },
    },

    # --------------------------------------------------------------------------
    # EXTRACT BITS - Extract specific bit range from response value
    # --------------------------------------------------------------------------
    {
        "name": "extract_bits_example",
        "match": {"status": 0x00},
        "set_fields": {
            "flag_bits": {
                "copy_from_response": "server_flags",
                "extract_bits": {
                    "start": 0,   # Starting bit position
                    "count": 4,   # Number of bits to extract
                },
                # Extracts bits 0-3 (4 LSBs) from server_flags
            },
        },
    },

    # --------------------------------------------------------------------------
    # SINGLE OPERATION - Apply one transformation
    # --------------------------------------------------------------------------
    {
        "name": "single_operation_example",
        "match": {"status": 0x00},
        "set_fields": {
            "derived_check": {
                "copy_from_response": "server_token",
                "operation": "and_mask",
                "value": 0xFF,  # Extract lowest byte
            },
        },
    },

    # ==========================================================================
    #  SECTION 6: TRANSFORM OPERATIONS - All Supported Operations
    # ==========================================================================

    # --------------------------------------------------------------------------
    # TRANSFORM PIPELINE - Chain multiple operations
    # --------------------------------------------------------------------------
    {
        "name": "transform_pipeline_example",
        "match": {"status": 0x00},
        "set_fields": {
            "derived_check": {
                "copy_from_response": "server_token",
                "transform": [
                    # Operations execute in order:

                    # ARITHMETIC OPERATIONS
                    # {"operation": "add_constant", "value": 10},
                    # {"operation": "subtract_constant", "value": 5},
                    # {"operation": "modulo", "value": 256},

                    # BITWISE OPERATIONS
                    {"operation": "and_mask", "value": 0x1F},      # Extract 5 LSBs
                    {"operation": "invert", "bit_width": 5},       # Invert within 5 bits
                    # {"operation": "or_mask", "value": 0x80},     # Set bit 7
                    # {"operation": "xor_constant", "value": 0xFF},# XOR with constant
                    # {"operation": "shift_left", "value": 2},     # Left shift by 2
                    # {"operation": "shift_right", "value": 4},    # Right shift by 4
                ],
            },
        },
    },

    # --------------------------------------------------------------------------
    # ALL TRANSFORM OPERATIONS REFERENCE (commented examples)
    # --------------------------------------------------------------------------
    # Uncomment and modify as needed:
    #
    # {"operation": "add_constant", "value": N}      # result = value + N
    # {"operation": "subtract_constant", "value": N} # result = value - N
    # {"operation": "modulo", "value": N}            # result = value % N
    #
    # {"operation": "and_mask", "value": 0xFF}       # result = value & mask
    # {"operation": "or_mask", "value": 0x80}        # result = value | mask
    # {"operation": "xor_constant", "value": 0xAA}   # result = value ^ constant
    #
    # {"operation": "shift_left", "value": N}        # result = value << N
    # {"operation": "shift_right", "value": N}       # result = value >> N
    #
    # {"operation": "invert", "bit_width": 8}        # result = ~value & ((1<<8)-1)
    #   IMPORTANT: Always specify bit_width for invert to avoid incorrect results
    #
]


# ==============================================================================
#  SECTION 7: STATE MODEL - Stateful Protocol Definition
# ==============================================================================

state_model = {
    "initial_state": "INIT",

    "states": [
        "INIT",        # Initial state
        "CONNECTED",   # After handshake
        "DATA",        # Data transfer mode
        "CLOSING",     # Graceful shutdown
    ],

    "transitions": [
        {
            "from": "INIT",
            "to": "CONNECTED",
            "message_type": "INIT",
        },
        {
            "from": "CONNECTED",
            "to": "DATA",
            "message_type": "DATA",
        },
        {
            "from": "DATA",
            "to": "DATA",
            "message_type": "DATA",  # Can stay in DATA
        },
        {
            "from": "DATA",
            "to": "CLOSING",
            "message_type": "CLOSE",
        },
        {
            "from": "CLOSING",
            "to": "INIT",
            "message_type": "ACK",
        },
    ],
}


# ==============================================================================
#  RESPONSE VALIDATOR
# ==============================================================================

def validate_response(response: bytes) -> bool:
    """
    Optional response validator (specification oracle).

    Returns:
        True if response is valid, False if it violates protocol spec.

    A False return is logged as a LOGICAL_FAILURE finding.
    """
    if len(response) < 5:
        return False

    # Check magic header
    if response[:4] != b"REF!":
        return False

    # Check status is valid
    status = response[4]
    if status > 0x01:
        return False

    return True
