"""
MQTT Protocol Plugin - Message Queuing Telemetry Transport (v3.1.1)

PURPOSE:
========
This plugin defines the MQTT protocol for fuzzing IoT message brokers.
MQTT is the dominant protocol for IoT device communication, making it
a critical target for security testing:

  - Ubiquitous: Millions of IoT devices (sensors, cameras, industrial)
  - Lightweight: Designed for constrained devices and networks
  - Broker-based: Central message broker is a high-value target
  - Growing attack surface: Smart homes, industrial control, healthcare

TRANSPORT:
==========
  - TCP port 1883 (unencrypted)
  - TCP port 8883 (TLS/SSL encrypted)

PROTOCOL STRUCTURE:
===================
MQTT uses a compact binary format with variable-length encoding:

  +------------------+------------------+------------------+
  | Fixed Header     | Variable Header  | Payload          |
  | (2+ bytes)       | (varies by type) | (varies by type) |
  +------------------+------------------+------------------+

FIXED HEADER (all packet types):
  Byte 1: [Packet Type (4 bits)][Flags (4 bits)]
  Byte 2+: Remaining Length (variable-length encoding, 1-4 bytes)

BIT FIELD SHOWCASE:
===================
MQTT's fixed header demonstrates several bit-level patterns:
  - Packet type (4 bits): CONNECT, PUBLISH, SUBSCRIBE, etc.
  - Flags (4 bits): Meaning varies by packet type
  - For PUBLISH: DUP(1) + QoS(2) + RETAIN(1)

REMAINING LENGTH ENCODING:
==========================
MQTT uses a clever variable-length integer encoding:
  - Each byte uses 7 bits for value, 1 bit as continuation flag
  - Allows encoding 0 to 268,435,455 in 1-4 bytes
  - Similar to protobuf varints

COMMON VULNERABILITIES FOUND BY FUZZING:
========================================
  - Buffer overflows in topic parsing
  - Memory exhaustion via large payloads or many subscriptions
  - Authentication bypass via malformed CONNECT
  - Denial of service via malformed packet sequences
  - Information disclosure via error messages

REFERENCES:
===========
  - OASIS MQTT v3.1.1 Specification
  - MQTT v5.0 Specification (different plugin needed)
  - Eclipse Mosquitto (popular open-source broker)
"""

__version__ = "1.0.0"
transport = "tcp"

# ==============================================================================
#  DATA MODEL - MQTT CONNECT Packet
# ==============================================================================
# The CONNECT packet is sent first by clients and is a rich fuzzing target.
# It contains authentication, protocol version, and session flags.

data_model = {
    "name": "MQTT_CONNECT",
    "description": "MQTT v3.1.1 CONNECT packet for broker authentication",

    "blocks": [
        # =====================================================================
        # FIXED HEADER (2+ bytes)
        # =====================================================================

        {
            "name": "packet_type",
            "type": "bits",
            "size": 4,
            "default": 1,              # 1 = CONNECT
            "mutable": False,          # Keep as CONNECT for this plugin

            # PACKET TYPE (4 bits):
            # Identifies the type of MQTT control packet.
            #
            # Types:
            #   1 = CONNECT (client to broker)
            #   2 = CONNACK (broker to client)
            #   3 = PUBLISH (both directions)
            #   4 = PUBACK (QoS 1 acknowledgment)
            #   5 = PUBREC (QoS 2 part 1)
            #   6 = PUBREL (QoS 2 part 2)
            #   7 = PUBCOMP (QoS 2 part 3)
            #   8 = SUBSCRIBE (client to broker)
            #   9 = SUBACK (broker to client)
            #   10 = UNSUBSCRIBE (client to broker)
            #   11 = UNSUBACK (broker to client)
            #   12 = PINGREQ (keepalive)
            #   13 = PINGRESP (keepalive response)
            #   14 = DISCONNECT (client to broker)
            #   0, 15 = Reserved
            "values": {
                1: "CONNECT",
                2: "CONNACK",
                3: "PUBLISH",
                4: "PUBACK",
                8: "SUBSCRIBE",
                12: "PINGREQ",
                14: "DISCONNECT",
            },
        },
        {
            "name": "flags",
            "type": "bits",
            "size": 4,
            "default": 0,              # CONNECT has no flags

            # FLAGS (4 bits):
            # For CONNECT packets, all flags must be 0.
            # For PUBLISH packets, this contains DUP, QoS, RETAIN.
            #
            # FUZZING INTEREST:
            # Setting non-zero flags for CONNECT tests validation.
            # Per spec, broker must close connection if flags != 0.
        },
        {
            "name": "remaining_length",
            "type": "uint8",
            "default": 0,              # Auto-calculated
            "is_size_field": True,
            "size_of": ["protocol_name_len", "protocol_name", "protocol_level",
                       "connect_flags_byte", "keep_alive", "client_id_len", "client_id"],

            # REMAINING LENGTH:
            # Number of bytes following this field.
            # For simplicity, this plugin uses a single-byte encoding
            # (valid for messages up to 127 bytes).
            #
            # VARIABLE-LENGTH ENCODING (for larger messages):
            # Each byte: [continuation_bit (1)][value_bits (7)]
            # If continuation bit is 1, another byte follows.
            #
            # FUZZING INTEREST:
            # - Mismatched remaining_length causes parsing issues
            # - Very large values test memory allocation
            # - Multi-byte encoding edge cases
        },

        # =====================================================================
        # VARIABLE HEADER - CONNECT specific
        # =====================================================================

        {
            "name": "protocol_name_len",
            "type": "uint16",
            "endian": "big",
            "default": 4,
            "is_size_field": True,
            "size_of": "protocol_name",
            "mutable": False,

            # PROTOCOL NAME LENGTH:
            # Length of the protocol name string.
            # For MQTT 3.1.1, this is always 4 ("MQTT").
            # For MQTT 3.1, this was 6 ("MQIsdp").
        },
        {
            "name": "protocol_name",
            "type": "string",
            "size": 4,
            "default": "MQTT",
            "mutable": False,

            # PROTOCOL NAME:
            # "MQTT" for version 3.1.1 and later.
            # "MQIsdp" for older version 3.1.
            #
            # FUZZING NOTE:
            # To test protocol name validation, create separate seeds
            # with different protocol names rather than fuzzing this field.
        },
        {
            "name": "protocol_level",
            "type": "uint8",
            "default": 4,              # 4 = MQTT 3.1.1

            # PROTOCOL LEVEL:
            # Version identifier for the protocol.
            #   3 = MQTT 3.1
            #   4 = MQTT 3.1.1
            #   5 = MQTT 5.0
            #
            # FUZZING INTEREST:
            # - Invalid levels test version negotiation
            # - Level 5 on a 3.1.1 broker tests compatibility handling
            "values": {
                3: "MQTT 3.1",
                4: "MQTT 3.1.1",
                5: "MQTT 5.0",
            },
        },

        # =====================================================================
        # CONNECT FLAGS - Rich bit field example
        # =====================================================================
        # The connect flags byte packs 7 distinct settings into 8 bits.

        {
            "name": "username_flag",
            "type": "bits",
            "size": 1,
            "default": 0,

            # USERNAME FLAG (bit 7):
            # If set, username is present in payload.
            # If username_flag=1 but no username provided, invalid packet.
        },
        {
            "name": "password_flag",
            "type": "bits",
            "size": 1,
            "default": 0,

            # PASSWORD FLAG (bit 6):
            # If set, password is present in payload.
            # Password flag can only be 1 if username_flag is 1.
            #
            # FUZZING INTEREST:
            # password_flag=1 with username_flag=0 is invalid per spec.
            # Tests if broker validates this constraint.
        },
        {
            "name": "will_retain",
            "type": "bits",
            "size": 1,
            "default": 0,

            # WILL RETAIN (bit 5):
            # If set, the Will Message is retained by broker.
            # Only meaningful if will_flag is 1.
        },
        {
            "name": "will_qos",
            "type": "bits",
            "size": 2,
            "default": 0,

            # WILL QOS (bits 4-3):
            # Quality of Service level for Will Message.
            #   0 = At most once (fire and forget)
            #   1 = At least once (acknowledged)
            #   2 = Exactly once (4-way handshake)
            #   3 = INVALID (reserved)
            #
            # FUZZING INTEREST:
            # will_qos=3 is invalid and tests error handling.
            "values": {
                0: "QoS 0",
                1: "QoS 1",
                2: "QoS 2",
                3: "INVALID",
            },
        },
        {
            "name": "will_flag",
            "type": "bits",
            "size": 1,
            "default": 0,

            # WILL FLAG (bit 2):
            # If set, a Will Message must be stored by the broker.
            # If will_flag=0, will_qos and will_retain must be 0.
        },
        {
            "name": "clean_session",
            "type": "bits",
            "size": 1,
            "default": 1,              # Start fresh

            # CLEAN SESSION (bit 1):
            # If set (1), broker discards any previous session state.
            # If clear (0), broker resumes previous session if available.
            #
            # FUZZING INTEREST:
            # clean_session=0 with new client_id tests session handling.
        },
        {
            "name": "reserved_bit",
            "type": "bits",
            "size": 1,
            "default": 0,
            "mutable": False,

            # RESERVED (bit 0):
            # Must be 0. Broker must close connection if set.
            # Set mutable=False to ensure valid packets by default.
        },

        # =====================================================================
        # KEEP ALIVE
        # =====================================================================

        {
            "name": "keep_alive",
            "type": "uint16",
            "endian": "big",
            "default": 60,             # 60 seconds

            # KEEP ALIVE:
            # Maximum time in seconds between control packets.
            # If no packets sent within keep_alive * 1.5, broker disconnects.
            #
            # FUZZING INTEREST:
            # - keep_alive=0 means no timeout (may enable resource exhaustion)
            # - Very large values test timeout handling
            # - Very small values test rapid ping requirements
        },

        # =====================================================================
        # PAYLOAD - Client Identifier
        # =====================================================================

        {
            "name": "client_id_len",
            "type": "uint16",
            "endian": "big",
            "default": 10,
            "is_size_field": True,
            "size_of": "client_id",

            # CLIENT ID LENGTH:
            # Length of the client identifier string.
            # Must be 1-23 characters for strict MQTT 3.1.1.
            # Many brokers accept longer client IDs.
        },
        {
            "name": "client_id",
            "type": "string",
            "max_size": 65535,
            "encoding": "utf-8",
            "default": "fuzz_client",

            # CLIENT ID:
            # Unique identifier for this client.
            # Used by broker to track session state.
            #
            # FUZZING INTEREST:
            # - Empty client_id (with clean_session=1) is valid
            # - Empty client_id (with clean_session=0) is invalid
            # - Very long client_ids test buffer handling
            # - Special characters test sanitization
            # - Duplicate client_ids test session takeover
        },
    ],

    # =========================================================================
    # SEED CORPUS
    # =========================================================================

    "seeds": [
        # Seed 1: Minimal CONNECT - clean session, no auth
        (
            b"\x10"                  # CONNECT packet type, no flags
            b"\x10"                  # Remaining length = 16
            b"\x00\x04MQTT"          # Protocol name
            b"\x04"                  # Protocol level (3.1.1)
            b"\x02"                  # Connect flags: clean_session=1
            b"\x00\x3c"              # Keep alive = 60 seconds
            b"\x00\x06client"        # Client ID = "client"
        ),

        # Seed 2: CONNECT with Will Message flags set
        (
            b"\x10"                  # CONNECT packet type
            b"\x18"                  # Remaining length = 24
            b"\x00\x04MQTT"          # Protocol name
            b"\x04"                  # Protocol level (3.1.1)
            b"\x0e"                  # Flags: clean=1, will=1, will_qos=1
            b"\x00\x3c"              # Keep alive = 60 seconds
            b"\x00\x0efuzz_will_test"  # Client ID
        ),

        # Seed 3: CONNECT with username flag (no actual username in payload)
        # This is technically invalid and tests broker validation
        (
            b"\x10"                  # CONNECT packet type
            b"\x10"                  # Remaining length
            b"\x00\x04MQTT"          # Protocol name
            b"\x04"                  # Protocol level
            b"\x82"                  # Flags: username=1, clean=1
            b"\x00\x3c"              # Keep alive
            b"\x00\x06client"        # Client ID
        ),

        # Seed 4: CONNECT with zero keep-alive (no timeout)
        (
            b"\x10"                  # CONNECT packet type
            b"\x10"                  # Remaining length
            b"\x00\x04MQTT"          # Protocol name
            b"\x04"                  # Protocol level
            b"\x02"                  # Connect flags: clean_session=1
            b"\x00\x00"              # Keep alive = 0 (infinite)
            b"\x00\x06client"        # Client ID
        ),

        # Seed 5: CONNECT with QoS 2 Will (highest reliability)
        (
            b"\x10"                  # CONNECT packet type
            b"\x18"                  # Remaining length
            b"\x00\x04MQTT"          # Protocol name
            b"\x04"                  # Protocol level
            b"\x16"                  # Flags: clean=1, will=1, will_qos=2
            b"\x00\x3c"              # Keep alive = 60
            b"\x00\x0eqos2_will_test"  # Client ID
        ),

        # Seed 6: CONNECT attempting MQTT 5.0 on 3.1.1 broker
        (
            b"\x10"                  # CONNECT packet type
            b"\x10"                  # Remaining length
            b"\x00\x04MQTT"          # Protocol name
            b"\x05"                  # Protocol level = 5 (MQTT 5.0)
            b"\x02"                  # Connect flags: clean_session=1
            b"\x00\x3c"              # Keep alive
            b"\x00\x06client"        # Client ID
        ),
    ],
}


# ==============================================================================
#  STATE MODEL - MQTT Connection Lifecycle
# ==============================================================================

state_model = {
    "initial_state": "DISCONNECTED",
    "states": ["DISCONNECTED", "CONNECTING", "CONNECTED"],
    "transitions": [
        {
            "from": "DISCONNECTED",
            "to": "CONNECTING",
            "message_type": "CONNECT",
        },
        {
            "from": "CONNECTING",
            "to": "CONNECTED",
            "message_type": "CONNACK",
            "expected_response": "CONNACK",
        },
        {
            "from": "CONNECTED",
            "to": "DISCONNECTED",
            "message_type": "DISCONNECT",
        },
    ],
}


# ==============================================================================
#  RESPONSE VALIDATOR
# ==============================================================================

def validate_response(response: bytes) -> bool:
    """
    Validate MQTT CONNACK response.

    CONNACK format:
      Byte 1: Packet type (0x20) and flags (0x00)
      Byte 2: Remaining length (2)
      Byte 3: Session present flag
      Byte 4: Return code
    """
    if len(response) < 4:
        return False

    # Check packet type is CONNACK (0x20)
    if response[0] != 0x20:
        return False

    # Check remaining length is 2
    if response[1] != 0x02:
        return False

    # Check return code is valid (0-5)
    return_code = response[3]
    if return_code > 5:
        return False

    return True
