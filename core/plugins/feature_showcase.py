"""
Feature Showcase Protocol Plugin
Version: 1.0.0

This plugin is designed to demonstrate all supported features of the fuzzing
engine's protocol implementation. It serves as a comprehensive example for
developers creating new plugins.
"""

__version__ = "1.0.0"

# ==============================================================================
#  1. Data Model (`data_model`)
# ==============================================================================
# The data_model defines the structure of the protocol's messages.
data_model = {
    "name": "FeatureShowcaseProtocol",
    "description": "A protocol that demonstrates all supported features.",

    # --------------------------------------------------------------------------
    #  Block Definitions
    # --------------------------------------------------------------------------
    # 'blocks' define the fields of a message in the order they appear.
    "blocks": [
        # --- Static Header ---
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"SHOW",
            "mutable": False,  # 'mutable: False' protects static fields from mutation.
        },
        {
            "name": "protocol_version",
            "type": "uint8",
            "default": 1,
            "mutable": False,
        },

        # --- Dynamic Header ---
        {
            "name": "header_len",
            "type": "uint8",
            "is_size_field": True,
            # The dynamic header includes three fields, so we point to all of them.
            "size_of": ["message_type", "flags", "session_id"],
        },
        {
            "name": "header_checksum",
            "type": "uint16",
            "endian": "little", # Demonstrates little-endian integer parsing.
            # NOTE: Checksums are handled via declarative behaviors (see core/protocol_behavior.py).
            # Supported operations: `increment` and `add_constant`. Example:
            # "behavior": {"operation": "add_constant", "value": 0x55}
            # Additional algorithms (e.g., CRC) can be modeled in the plugin until native support lands.
            "default": 0xDEAD,
        },
        {
            "name": "message_type",
            "type": "uint8",
            "default": 0x01,
            "values": {  # 'values' creates a named enum for a field.
                0x01: "HANDSHAKE_REQUEST",
                0x02: "HANDSHAKE_RESPONSE",
                0x10: "DATA_STREAM",
                0x11: "DATA_ACK",
                0xFE: "HEARTBEAT",
                0xFF: "TERMINATE",
            },
        },
        {
            "name": "flags",
            "type": "uint16", # Can be used to fuzz bit fields as a single integer.
            "endian": "big", # Default is 'big', but explicitly stated here.
            "default": 0,
        },
        {
            "name": "session_id",
            "type": "uint64", # Demonstrates a 64-bit integer.
            "default": 0,
        },

        # --- Payload ---
        {
            "name": "payload_len",
            "type": "uint32",
            "is_size_field": True, # This field's value is derived from another field's length.
            "size_of": "payload",  # It will be auto-calculated as the length of the 'payload' field.
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 8192, # 'max_size' for variable-length byte arrays.
            "default": b"",
        },
        {
            "name": "metadata_len",
            "type": "uint16",
            "is_size_field": True,
            "size_of": "metadata",
        },
        {
            "name": "metadata",
            "type": "string", # A string field.
            "max_size": 128,
            "encoding": "utf-16-le", # Specifies the character encoding.
            "references": ["payload_len", "payload"], # Highlights dependency on earlier fields.
            "default": "",
        },
        {
            "name": "telemetry_counter",
            "type": "uint16",
            "default": 0,
            "mutable": False,
            "behavior": {
                "operation": "increment",
                "initial": 0,
                "step": 1,
            },
        },
        {
            "name": "opcode_bias",
            "type": "uint8",
            "default": 0,
            "mutable": False,
            "references": "message_type",
            "behavior": {
                "operation": "add_constant",
                "value": 0x3,
            },
        },
        {
            "name": "trace_cookie",
            "type": "uint32",
            "default": 0,
            "mutable": False,
        },

        # --- Footer ---
        {
            "name": "footer_marker",
            "type": "bytes",
            "size": 2,
            "default": b"\r\n",
            "mutable": False,
        },
    ],

    # --------------------------------------------------------------------------
    #  Seed Corpus
    # --------------------------------------------------------------------------
    # 'seeds' provide the fuzzer with initial valid inputs to mutate.
    "seeds": [
        # Seed 1: A valid HANDSHAKE_REQUEST
        (b"SHOW\x01\x0B\xAD\xDE\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01"
         b"\x00\x00\x00\x0C" b"Hello World!" b"\x00\x00" b"\x00\x00" b"\x00" b"\x00\x00\x00\x00" b"\r\n"),

        # Seed 2: A valid DATA_STREAM message
        (b"SHOW\x01\x0B\xAD\xDE\x10\x00\x01\x01\x02\x03\x04\x05\x06\x07\x08"
         b"\x00\x00\x00\x10" b"Some stream data" b"\x00\x00" b"\x00\x00" b"\x00" b"\x00\x00\x00\x00" b"\r\n"),

        # Seed 3: A valid TERMINATE message with no payload
        (b"SHOW\x01\x0B\xAD\xDE\xFF\x00\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF"
         b"\x00\x00\x00\x00" b"\x00\x00" b"\x00\x00" b"\x00" b"\x00\x00\x00\x00" b"\r\n"),
    ],
}

# ------------------------------------------------------------------------------
#  Response Model
# ------------------------------------------------------------------------------
# Define how server responses should be parsed so we can plan follow-up messages.
response_model = {
    "name": "FeatureShowcaseResponses",
    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"SHOW",
        },
        {
            "name": "protocol_version",
            "type": "uint8",
            "default": 1,
        },
        {
            "name": "status",
            "type": "uint8",
            "values": {
                0x00: "OK",
                0x01: "BUSY",
                0xFF: "ERROR",
            },
            "default": 0x00,
        },
        {
            "name": "session_token",
            "type": "uint64",
            "default": 0,
        },
        {
            "name": "server_nonce",
            "type": "uint32",
            "default": 0,
        },
        {
            "name": "trace_id",
            "type": "uint32",
            "default": 0,
        },
        {
            "name": "details_length",
            "type": "uint16",
            "is_size_field": True,
            "size_of": "details",
        },
        {
            "name": "details",
            "type": "bytes",
            "max_size": 512,
            "default": b"",
        },
        {
            "name": "advice_length",
            "type": "uint8",
            "is_size_field": True,
            "size_of": "advice",
        },
        {
            "name": "advice",
            "type": "string",
            "max_size": 64,
            "default": "",
        },
    ],
}

# ------------------------------------------------------------------------------
#  Response Handlers
# ------------------------------------------------------------------------------
# Declarative rules for crafting follow-up requests after parsing responses.
response_handlers = [
    {
        "name": "sync_session_token",
        "match": {"status": [0x00, 0x01]},
        "set_fields": {
            "message_type": 0x10,  # Switch to DATA_STREAM after handshake succeeds
            "session_id": {"copy_from_response": "session_token"},
            "trace_cookie": {"copy_from_response": "trace_id"},
        },
    }
]

# ==============================================================================
#  2. State Model (`state_model`)
# ==============================================================================
# The state_model defines the protocol's state machine, enabling stateful fuzzing.
state_model = {
    "initial_state": "UNINITIALIZED",

    "states": ["UNINITIALIZED", "HANDSHAKE_SENT", "ESTABLISHED", "CLOSED"],

    "transitions": [
        {
            "from": "UNINITIALIZED",
            "to": "HANDSHAKE_SENT",
            "message_type": "HANDSHAKE_REQUEST",
            "expected_response": "HANDSHAKE_RESPONSE", # Checks that a response is received.
        },
        {
            "from": "HANDSHAKE_SENT",
            "to": "ESTABLISHED",
            "message_type": "DATA_STREAM", # Assumes handshake was implicitly accepted.
        },
        {
            "from": "ESTABLISHED",
            "to": "ESTABLISHED",
            "message_type": "DATA_STREAM", # A loop to allow multiple data messages.
        },
        {
            "from": "ESTABLISHED",
            "to": "ESTABLISHED",
            "message_type": "HEARTBEAT",
        },
        {
            "from": "ESTABLISHED",
            "to": "CLOSED",
            "message_type": "TERMINATE",
        },
        {
            # This allows transitioning from HANDSHAKE_SENT directly to CLOSED.
            "from": "HANDSHAKE_SENT",
            "to": "CLOSED",
            "message_type": "TERMINATE",
        },
    ],
}

# ==============================================================================
#  3. Response Validator (`validate_response`)
# ==============================================================================
# An optional function to perform application-specific validation on responses.
# This acts as a "logic oracle" to detect non-crash bugs.
def validate_response(response: bytes) -> bool:
    """
    Validates the logical correctness of a response from the target.

    Args:
        response: The raw response bytes from the target application.

    Returns:
        True if the response is logically valid, False otherwise.
    """
    if len(response) < 4:
        return False # Response is too short to be valid.

    # Check 1: The response must start with the magic bytes "RESP".
    if response[:4] != b"RESP":
        return False

    # Check 2: If the response is an error message (type 0xFF), it must
    # have a non-empty payload explaining the error.
    try:
        # This is a simplified parse; a real validator might use the ProtocolParser.
        response_type = response[4]
        payload_len = int.from_bytes(response[5:9], 'big')
        if response_type == 0xFF and payload_len == 0:
            return False # Error message with no explanation is a logic bug.
    except IndexError:
        return False # Malformed response that didn't fit our expected structure.

    return True
