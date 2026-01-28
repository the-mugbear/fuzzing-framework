"""
CoAP Protocol Plugin - Constrained Application Protocol (RFC 7252)

PURPOSE:
========
This plugin defines the CoAP protocol for fuzzing IoT devices and gateways.
CoAP is the "HTTP for IoT" - a lightweight REST protocol designed for
constrained devices:

  - Smart home devices (lights, thermostats, sensors)
  - Industrial IoT (machinery monitoring, asset tracking)
  - Wearables and health monitors
  - Building automation systems
  - Smart city infrastructure

CoAP vs MQTT:
=============
  - MQTT: Pub/sub messaging, broker-centric, TCP
  - CoAP: Request/response REST, peer-to-peer, UDP

TRANSPORT:
==========
  - UDP port 5683 (CoAP)
  - UDP port 5684 (CoAPS with DTLS encryption)

PROTOCOL STRUCTURE:
===================
CoAP has a compact 4-byte base header with optional extensions:

  +------------------+------------------+------------------+------------------+
  | Ver|Type|TKL     | Code             | Message ID                          |
  | (8 bits)         | (8 bits)         | (16 bits)                           |
  +------------------+------------------+------------------+------------------+
  | Token (0-8 bytes, length = TKL)                                           |
  +------------------+------------------+------------------+------------------+
  | Options (variable, each: delta + length + value)                          |
  +------------------+------------------+------------------+------------------+
  | 0xFF             | Payload (if present)                                   |
  +------------------+------------------+------------------+------------------+

BIT FIELD SHOWCASE:
===================
The first byte packs three fields:
  - Version (2 bits): Must be 1
  - Type (2 bits): CON, NON, ACK, RST
  - Token Length (4 bits): 0-8

The code byte is split into class and detail:
  - Class (3 bits): 0=request, 2=success, 4=client error, 5=server error
  - Detail (5 bits): Specific code within class

COMMON VULNERABILITIES FOUND BY FUZZING:
========================================
  - Buffer overflows in option parsing
  - Integer overflows in block transfers
  - Denial of service via resource exhaustion
  - Path traversal via URI-Path options
  - Information disclosure via .well-known/core
  - Amplification attacks (like DNS)

REFERENCES:
===========
  - RFC 7252: Constrained Application Protocol (CoAP)
  - RFC 7641: Observing Resources in CoAP
  - RFC 7959: Block-Wise Transfers in CoAP
"""

__version__ = "1.0.0"
transport = "udp"

# ==============================================================================
#  DATA MODEL - CoAP Request
# ==============================================================================

data_model = {
    "name": "CoAP",
    "description": "Constrained Application Protocol IoT request (RFC 7252)",

    "blocks": [
        # =====================================================================
        # FIRST BYTE - Bit Fields (Version, Type, Token Length)
        # =====================================================================

        {
            "name": "version",
            "type": "bits",
            "size": 2,
            "default": 1,              # Must be 1 for CoAP
            "mutable": False,

            # VERSION (2 bits):
            # CoAP protocol version. Currently must be 1.
            # Other values are reserved and should be rejected.
            #
            # FUZZING NOTE:
            # To test version validation, create separate seeds with
            # version 0, 2, or 3 rather than fuzzing this field.
        },
        {
            "name": "type",
            "type": "bits",
            "size": 2,
            "default": 0,              # 0 = CON (Confirmable)

            # TYPE (2 bits):
            # Message type determining reliability and acknowledgment.
            #
            # Values:
            #   0 = CON (Confirmable) - Requires ACK
            #   1 = NON (Non-confirmable) - No ACK needed
            #   2 = ACK (Acknowledgment)
            #   3 = RST (Reset) - Error response
            #
            # FUZZING INTEREST:
            # - CON requests test reliable delivery
            # - NON requests test fire-and-forget handling
            # - ACK/RST as requests test state validation
            "values": {
                0: "CON",
                1: "NON",
                2: "ACK",
                3: "RST",
            },
        },
        {
            "name": "token_length",
            "type": "bits",
            "size": 4,
            "default": 4,              # 4-byte token

            # TOKEN LENGTH (4 bits):
            # Length of the token field (0-8 bytes).
            #
            # Values 9-15 are reserved and must cause message rejection.
            #
            # FUZZING INTEREST:
            # - TKL=0 with token data tests parsing
            # - TKL=9+ (reserved) tests validation
            # - TKL mismatch with actual token size
        },

        # =====================================================================
        # CODE BYTE - Split into Class and Detail
        # =====================================================================

        {
            "name": "code_class",
            "type": "bits",
            "size": 3,
            "default": 0,              # 0 = Request

            # CODE CLASS (3 bits):
            # High-level category of the message.
            #
            # Values:
            #   0 = Request (GET, POST, PUT, DELETE)
            #   2 = Success response (2.01-2.05)
            #   4 = Client error (4.00-4.15)
            #   5 = Server error (5.00-5.05)
            #   1, 3, 6, 7 = Reserved
            #
            # For requests, class should be 0.
            "values": {
                0: "Request",
                2: "Success",
                4: "Client Error",
                5: "Server Error",
            },
        },
        {
            "name": "code_detail",
            "type": "bits",
            "size": 5,
            "default": 1,              # 0.01 = GET

            # CODE DETAIL (5 bits):
            # Specific code within the class.
            #
            # For requests (class 0):
            #   01 = GET (retrieve resource)
            #   02 = POST (create/process)
            #   03 = PUT (update/create)
            #   04 = DELETE (remove)
            #
            # The combination class.detail gives codes like:
            #   0.01 = GET request
            #   2.05 = Content response
            #   4.04 = Not Found
            #   5.00 = Internal Server Error
            #
            # FUZZING INTEREST:
            # - Undefined request codes (0.00, 0.05+)
            # - Response codes sent as requests
            "values": {
                1: "GET",
                2: "POST",
                3: "PUT",
                4: "DELETE",
            },
        },

        # =====================================================================
        # MESSAGE ID (2 bytes)
        # =====================================================================

        {
            "name": "message_id",
            "type": "uint16",
            "endian": "big",
            "default": 0x0001,

            # MESSAGE ID:
            # 16-bit identifier for matching ACKs to requests
            # and detecting duplicate messages.
            #
            # Should be different for each CON/NON message.
            # ACK/RST use the same ID as the message being acknowledged.
            #
            # FUZZING INTEREST:
            # - Duplicate message IDs test deduplication
            # - ID=0 may have special handling
        },

        # =====================================================================
        # TOKEN (0-8 bytes, length specified by TKL)
        # =====================================================================

        {
            "name": "token",
            "type": "bytes",
            "max_size": 8,
            "default": b"\x01\x02\x03\x04",  # 4-byte token

            # TOKEN:
            # Client-generated token to match requests with responses.
            # Used for request/response correlation, especially
            # for observing resources (RFC 7641).
            #
            # Length must match token_length field.
            #
            # FUZZING INTEREST:
            # - Token length mismatch
            # - Empty token (TKL=0)
            # - Maximum length token (8 bytes)
        },

        # =====================================================================
        # OPTIONS (Variable length)
        # =====================================================================
        # Options use delta encoding: each option number is encoded as
        # delta from the previous option number.
        #
        # Format per option:
        #   4 bits: Delta (0-12, 13=ext1, 14=ext2, 15=reserved)
        #   4 bits: Length (0-12, 13=ext1, 14=ext2, 15=payload marker)
        #   [Extended delta if delta=13 or 14]
        #   [Extended length if length=13 or 14]
        #   [Value bytes]

        {
            "name": "options",
            "type": "bytes",
            "max_size": 256,
            "default": b"\xB5" b"hello",  # Uri-Path option with "hello"

            # OPTIONS:
            # CoAP options encode metadata about the request.
            #
            # Common options:
            #   3 = Uri-Host (hostname)
            #   7 = Uri-Port (port number)
            #   11 = Uri-Path (path segment, repeatable)
            #   12 = Content-Format (media type)
            #   14 = Max-Age (cache duration)
            #   15 = Uri-Query (query parameter)
            #   17 = Accept (preferred response format)
            #
            # OPTION ENCODING EXAMPLE:
            # To encode Uri-Path (option 11) with value "hello":
            #   - Delta from 0 to 11 = 11 (fits in 4 bits)
            #   - Length = 5 ("hello")
            #   - First byte: 0xB5 (delta=11, length=5)
            #   - Value: "hello"
            #
            # FUZZING TARGETS:
            # - Invalid delta values (15)
            # - Length mismatch with actual value
            # - Critical options with invalid values
            # - Unknown options (test ignore behavior)
            # - Very long option values
        },

        # =====================================================================
        # PAYLOAD MARKER AND PAYLOAD (Optional)
        # =====================================================================

        {
            "name": "payload_marker",
            "type": "uint8",
            "default": 0xFF,
            "mutable": False,

            # PAYLOAD MARKER:
            # 0xFF byte indicates start of payload.
            # Only present if there is a payload.
            #
            # Note: If no payload, omit this byte entirely.
            # For simplicity, this plugin always includes it.
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 1024,
            "default": b"",

            # PAYLOAD:
            # Request body (for POST/PUT) or response body.
            #
            # Format depends on Content-Format option:
            # - 0 = text/plain
            # - 40 = application/link-format
            # - 41 = application/xml
            # - 42 = application/octet-stream
            # - 47 = application/exi
            # - 50 = application/json
            # - 60 = application/cbor
            #
            # FUZZING INTEREST:
            # - Large payloads test memory handling
            # - Content-Format mismatch tests parsing
            # - Malformed JSON/XML/CBOR
        },
    ],

    # =========================================================================
    # SEED CORPUS
    # =========================================================================

    "seeds": [
        # Seed 1: Simple GET request for root resource
        # Ver=1, Type=0 (CON), TKL=4 -> first byte = 0x44
        # Code = 0.01 (GET) -> 0x01
        (
            b"\x44"                  # Ver=1, Type=CON, TKL=4
            b"\x01"                  # Code: 0.01 (GET)
            b"\x00\x01"              # Message ID
            b"\x01\x02\x03\x04"      # Token (4 bytes)
            # No options, no payload
        ),

        # Seed 2: GET /.well-known/core (resource discovery)
        (
            b"\x44"                  # Ver=1, Type=CON, TKL=4
            b"\x01"                  # Code: GET
            b"\x00\x02"              # Message ID
            b"\xAB\xCD\xEF\x01"      # Token
            b"\xBB"                  # Uri-Path delta=11, len=11
            b".well-known"           # Path segment 1
            b"\x04"                  # Uri-Path delta=0, len=4
            b"core"                  # Path segment 2
        ),

        # Seed 3: GET with Uri-Path option
        (
            b"\x44"                  # Ver=1, Type=CON, TKL=4
            b"\x01"                  # Code: GET
            b"\x00\x03"              # Message ID
            b"\x11\x22\x33\x44"      # Token
            b"\xB5"                  # Uri-Path delta=11, len=5
            b"hello"                 # Path: /hello
        ),

        # Seed 4: POST with JSON payload
        (
            b"\x44"                  # Ver=1, Type=CON, TKL=4
            b"\x02"                  # Code: 0.02 (POST)
            b"\x00\x04"              # Message ID
            b"\xDE\xAD\xBE\xEF"      # Token
            b"\xB4"                  # Uri-Path delta=11, len=4
            b"data"                  # Path: /data
            b"\x11"                  # Content-Format delta=1, len=1
            b"\x32"                  # Content-Format=50 (application/json)
            b"\xFF"                  # Payload marker
            b'{"value": 42}'        # JSON payload
        ),

        # Seed 5: PUT request to update resource
        (
            b"\x44"                  # Ver=1, Type=CON, TKL=4
            b"\x03"                  # Code: 0.03 (PUT)
            b"\x00\x05"              # Message ID
            b"\xCA\xFE\xBA\xBE"      # Token
            b"\xB6"                  # Uri-Path delta=11, len=6
            b"config"                # Path: /config
            b"\xFF"                  # Payload marker
            b"key=value"             # Plain text payload
        ),

        # Seed 6: DELETE request
        (
            b"\x44"                  # Ver=1, Type=CON, TKL=4
            b"\x04"                  # Code: 0.04 (DELETE)
            b"\x00\x06"              # Message ID
            b"\xF0\x0D\xF0\x0D"      # Token
            b"\xB4"                  # Uri-Path delta=11, len=4
            b"temp"                  # Path: /temp
        ),

        # Seed 7: Non-confirmable GET (fire and forget)
        # Type=1 (NON) -> first byte = 0x54
        (
            b"\x54"                  # Ver=1, Type=NON, TKL=4
            b"\x01"                  # Code: GET
            b"\x00\x07"              # Message ID
            b"\x12\x34\x56\x78"      # Token
            b"\xB6"                  # Uri-Path
            b"sensor"                # Path: /sensor
        ),

        # Seed 8: GET with multiple path segments and query
        (
            b"\x44"                  # Ver=1, Type=CON, TKL=4
            b"\x01"                  # Code: GET
            b"\x00\x08"              # Message ID
            b"\xAA\xBB\xCC\xDD"      # Token
            b"\xB3"                  # Uri-Path delta=11, len=3
            b"api"                   # /api
            b"\x02"                  # Uri-Path delta=0, len=2
            b"v1"                    # /api/v1
            b"\x05"                  # Uri-Path delta=0, len=5
            b"users"                 # /api/v1/users
            b"\x46"                  # Uri-Query delta=4, len=6
            b"limit=10"              # ?limit=10
        ),

        # Seed 9: Empty token (TKL=0)
        (
            b"\x40"                  # Ver=1, Type=CON, TKL=0
            b"\x01"                  # Code: GET
            b"\x00\x09"              # Message ID
            # No token
            b"\xB4"                  # Uri-Path
            b"test"                  # /test
        ),

        # Seed 10: Maximum token length (8 bytes)
        (
            b"\x48"                  # Ver=1, Type=CON, TKL=8
            b"\x01"                  # Code: GET
            b"\x00\x0A"              # Message ID
            b"\x01\x02\x03\x04\x05\x06\x07\x08"  # 8-byte token
            b"\xB4"                  # Uri-Path
            b"test"                  # /test
        ),
    ],
}


# ==============================================================================
#  STATE MODEL
# ==============================================================================
# CoAP has simple request/response semantics with optional observe.

state_model = {
    "initial_state": "IDLE",
    "states": ["IDLE", "REQUEST_SENT", "OBSERVING"],
    "transitions": [
        {
            "from": "IDLE",
            "to": "REQUEST_SENT",
            "message_type": "REQUEST",
        },
        {
            "from": "REQUEST_SENT",
            "to": "IDLE",
            "message_type": "REQUEST",
        },
        {
            "from": "REQUEST_SENT",
            "to": "OBSERVING",
            "message_type": "OBSERVE",
        },
        {
            "from": "OBSERVING",
            "to": "IDLE",
            "message_type": "CANCEL",
        },
    ],
}


# ==============================================================================
#  RESPONSE VALIDATOR
# ==============================================================================

def validate_response(response: bytes) -> bool:
    """
    Validate CoAP response.

    Checks:
    - Minimum length (4 bytes for header)
    - Version is 1
    - Code class is valid for response (2, 4, or 5)
    - Token length is valid (0-8)
    """
    if len(response) < 4:
        return False

    first_byte = response[0]
    version = (first_byte >> 6) & 0x03
    tkl = first_byte & 0x0F

    # Check version is 1
    if version != 1:
        return False

    # Check token length is valid
    if tkl > 8:
        return False

    # Check code class (second byte, upper 3 bits)
    code_class = (response[1] >> 5) & 0x07

    # Valid response classes: 2 (success), 4 (client error), 5 (server error)
    # Also allow ACK/RST which may have class 0
    if code_class not in (0, 2, 4, 5):
        return False

    # Verify message is long enough for token
    if len(response) < 4 + tkl:
        return False

    return True
