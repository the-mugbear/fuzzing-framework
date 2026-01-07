"""
Feature Showcase Protocol Plugin
==================================
Version: 1.0.0
Author: Fuzzing Framework Team

OVERVIEW
--------
This plugin demonstrates ALL supported features of the fuzzing framework's
protocol implementation system. It is intentionally comprehensive and serves
as both:
  1. A reference implementation for plugin developers
  2. A testing ground for verifying framework capabilities
  3. An educational tool with extensive inline documentation

This plugin pairs with tests/feature_showcase_server.py, which implements
a compliant server that responds to this protocol. Together they form a
complete example for learning the framework.

WHAT YOU'LL LEARN
-----------------
✓ How to define protocol message structures (data_model)
✓ All supported field types (bytes, integers, strings)
✓ Size fields and automatic length calculation
✓ Field behaviors (increment, add_constant)
✓ Field dependencies and references
✓ Endianness specification
✓ Response models for parsing server replies
✓ Response handlers for stateful protocol behavior
✓ State machines for multi-step protocol flows
✓ Response validation (logic oracles)
✓ Seed corpus creation

QUICK START
-----------
1. Review this file top-to-bottom to understand each feature
2. Run the feature_showcase_server: python tests/feature_showcase_server.py
3. Use the Plugin Explorer UI to visualize the protocol structure
4. Use the State Walker UI to test protocol transitions
5. Create your own plugin by copying sections you need

Let's begin!
"""

__version__ = "1.0.0"
transport = "tcp"

# ==============================================================================
#  SECTION 1: DATA MODEL (Request/Outbound Messages)
# ==============================================================================
# The `data_model` defines the STRUCTURE of messages your fuzzer sends to the
# target application. Think of it as a template that describes:
#   - What fields exist in a message
#   - What order they appear in (top to bottom = left to right in bytes)
#   - What type each field is (integer, bytes, string)
#   - Default values for creating baseline seeds
#   - Which fields can be mutated vs. which should stay fixed
#
# The fuzzer uses this model to:
#   1. Parse seed inputs into individual fields
#   2. Generate new test cases by mutating individual fields
#   3. Serialize mutated fields back into bytes for transmission
#   4. Automatically calculate length fields and apply behaviors
#
# IMPORTANT: This is for OUTBOUND messages (fuzzer → target).
#            For parsing INBOUND responses, see `response_model` below.

data_model = {
    # -------------------------------------------------------------------------
    # Protocol Metadata
    # -------------------------------------------------------------------------
    # These fields help identify the protocol in the UI and logs.

    "name": "FeatureShowcaseProtocol",
    "description": "A comprehensive demonstration of all framework features",

    # -------------------------------------------------------------------------
    # Block Definitions
    # -------------------------------------------------------------------------
    # The `blocks` list defines all message fields IN ORDER.
    # Each block is a dictionary with these common attributes:
    #
    #   REQUIRED:
    #     - name: Unique identifier for this field
    #     - type: Data type (see TYPE REFERENCE below)
    #
    #   OPTIONAL:
    #     - size: Fixed size in bytes (for fixed-length fields)
    #     - max_size: Maximum size in bytes (for variable-length fields)
    #     - default: Initial/baseline value for this field
    #     - mutable: Whether the fuzzer can mutate this field (default: True)
    #     - endian: Byte order for integers ("big" or "little", default: "big")
    #     - encoding: Character encoding for strings (default: "utf-8")
    #     - is_size_field: Mark this as a length field (auto-calculated)
    #     - size_of: Which field(s) this length field describes
    #     - behavior: Automatic transformations applied to this field
    #     - references: Documents which other fields this depends on
    #     - values: Enum mapping for documentation (doesn't enforce validation)
    #
    # TYPE REFERENCE:
    #   - "bytes": Raw byte array (use for binary data, magic values, etc.)
    #   - "uint8/16/32/64": Unsigned integers (1, 2, 4, 8 bytes)
    #   - "int8/16/32/64": Signed integers (1, 2, 4, 8 bytes)
    #   - "string": Text field (encoded according to 'encoding' parameter)

    "blocks": [
        # =====================================================================
        # PART 1: STATIC HEADER
        # =====================================================================
        # Static headers typically contain:
        #   - Magic bytes (protocol identifiers)
        #   - Version numbers
        #   - Other values that should NOT be fuzzed
        #
        # TIP: Set `mutable: False` to protect fields from mutation while
        #      still allowing length fields and behaviors to update them.

        {
            "name": "magic",
            "type": "bytes",           # Raw byte array type
            "size": 4,                 # Exactly 4 bytes (fixed length)
            "default": b"SHOW",        # Magic value identifying this protocol
            "mutable": False,          # NEVER mutate - required for target to accept message

            # WHY mutable: False?
            # The target server REQUIRES this exact value to recognize the protocol.
            # Fuzzing it would just result in the message being rejected immediately,
            # wasting test cases. Focus fuzzing on fields that exercise logic.
        },
        {
            "name": "protocol_version",
            "type": "uint8",           # 1-byte unsigned integer (0-255)
            "default": 1,              # We're using version 1 of this protocol
            "mutable": False,          # Don't fuzz version - keeps tests focused

            # NOTE: If you want to test version negotiation bugs, create separate
            # seeds with different versions rather than fuzzing this field.
        },

        # =====================================================================
        # PART 2: DYNAMIC HEADER WITH LENGTH FIELD
        # =====================================================================
        # Many protocols have a "header length" field that tells the parser
        # how many bytes to read for the header. This demonstrates:
        #   1. Size fields that auto-calculate
        #   2. Size fields that cover MULTIPLE other fields
        #   3. Little-endian integers

        {
            "name": "header_len",
            "type": "uint8",
            "is_size_field": True,     # This field's value is AUTO-CALCULATED

            # The fuzzer will automatically set this to the TOTAL size of
            # these three fields combined:
            "size_of": ["message_type", "flags", "session_id"],

            # HOW IT WORKS:
            # Before sending a message, the framework calculates:
            #   header_len = sizeof(message_type) + sizeof(flags) + sizeof(session_id)
            #              = 1 byte + 2 bytes + 8 bytes = 11 bytes
            #
            # Even if mutations change the VALUES in those fields, the SIZE
            # stays the same, so this correctly reflects the header length.
            #
            # TIP: If you had variable-length fields in the header (like a
            # variable-length string), this would automatically adjust!
        },
        {
            "name": "header_checksum",
            "type": "uint16",          # 2-byte unsigned integer
            "endian": "little",        # Little-endian byte order (LSB first)
            "default": 0xDEAD,         # Recognizable default value

            # ENDIANNESS EXAMPLE:
            # Value 0xDEAD in different endianness:
            #   Big-endian:    DE AD (most significant byte first)
            #   Little-endian: AD DE (least significant byte first)
            #
            # Many x86/x64 protocols use little-endian. Network protocols
            # typically use big-endian (network byte order).

            # CHECKSUM NOTE:
            # Currently the framework supports `increment` and `add_constant`
            # behaviors. For true checksums (CRC, MD5, etc.), you can:
            #   1. Use the State Walker to manually craft valid messages
            #   2. Implement custom checksum logic in your test harness
            #   3. Let the fuzzer fuzz invalid checksums to find bugs!
            #
            # Invalid checksums can find bugs in checksum validation logic.
        },

        # =====================================================================
        # PART 3: MESSAGE TYPE WITH ENUMERATION
        # =====================================================================
        # The `values` field creates a documented enumeration. This doesn't
        # enforce validation - it's for documentation and UI display.

        {
            "name": "message_type",
            "type": "uint8",
            "default": 0x01,           # Default to HANDSHAKE_REQUEST

            # The `values` dictionary maps numeric values to symbolic names.
            # BENEFITS:
            #   1. Plugin Explorer shows "HANDSHAKE_REQUEST" instead of "1"
            #   2. State Walker displays message types by name
            #   3. Logs are more readable
            #   4. Documents valid message types for developers
            #
            # NOTE: The fuzzer WILL mutate this to invalid values (e.g., 0x03)
            # to find bugs in message type validation!
            "values": {
                0x01: "HANDSHAKE_REQUEST",  # Initial connection setup
                0x02: "HANDSHAKE_RESPONSE",  # Not sent by client, but documented
                0x10: "DATA_STREAM",         # Send data to server
                0x11: "DATA_ACK",            # Acknowledge data (if needed)
                0xFE: "HEARTBEAT",           # Keep-alive message
                0xFF: "TERMINATE",           # Close connection gracefully
            },

            # TIP: Use hex values (0x01) instead of decimal (1) for
            # bit-oriented protocols to make patterns clearer.
        },
        {
            "name": "flags",
            "type": "uint16",          # 2-byte field for bit flags
            "endian": "big",           # Big-endian (this is the default, but shown explicitly)
            "default": 0,              # No flags set by default

            # BIT FLAGS PATTERN:
            # In real protocols, this might be:
            #   Bit 0 (0x0001): ENCRYPTED
            #   Bit 1 (0x0002): COMPRESSED
            #   Bit 2 (0x0004): FRAGMENTED
            #   Bit 15 (0x8000): DEBUG_MODE
            #
            # The fuzzer treats this as a single uint16 and will mutate it to
            # random values, which tests all combinations of flags including
            # invalid/reserved bit patterns.
            #
            # TIP: If you want to fuzz individual bits, you could model each
            # as a separate uint8 field and use behaviors to combine them.
        },
        {
            "name": "session_id",
            "type": "uint64",          # 8-byte unsigned integer (huge range!)
            "default": 0,              # Start with no session

            # STATEFUL PROTOCOL PATTERN:
            # This field demonstrates response-driven mutations. After a
            # HANDSHAKE_RESPONSE, the server sends a session_token in the
            # response. Our response_handler (see below) automatically copies
            # that token into this field for subsequent messages.
            #
            # This lets the fuzzer maintain protocol state across messages!
            #
            # WHY uint64?
            # Session tokens are often large random values to prevent
            # guessing. A 64-bit space provides 18 quintillion possibilities.
        },

        # =====================================================================
        # PART 4: VARIABLE-LENGTH PAYLOAD WITH SIZE FIELD
        # =====================================================================
        # This is the most common pattern in binary protocols:
        #   1. A length field (uint16/uint32) says how many bytes follow
        #   2. A variable-length data field contains the actual content
        #
        # The framework automatically keeps these synchronized!

        {
            "name": "payload_len",
            "type": "uint32",          # 4-byte length (supports up to 4GB payloads)
            "is_size_field": True,     # Auto-calculated from payload size
            "size_of": "payload",      # Points to the field we're measuring

            # AUTO-CALCULATION:
            # Before serializing a message, the framework:
            #   1. Looks at the current size of the "payload" field
            #   2. Sets payload_len = len(payload)
            #   3. Serializes payload_len as a uint32
            #
            # This happens AFTER mutations, so even if the fuzzer changes
            # the payload to random data, the length field stays correct.
            #
            # WHY THIS MATTERS:
            # Most length field bugs are in the PARSING logic (off-by-one,
            # integer overflow, etc.), not in valid length fields. The fuzzer
            # can still find these bugs by:
            #   - Sending payloads of extreme sizes (0, max_size, etc.)
            #   - Crafting specific payload content that triggers bugs
            #   - Testing the parser's buffer allocation logic
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 8192,          # Up to 8KB of data
            "default": b"",            # Empty by default

            # VARIABLE-LENGTH FIELDS:
            # Use `max_size` instead of `size` for fields that can vary.
            # The fuzzer will:
            #   - Generate payloads of different sizes (0 to max_size)
            #   - Mutate the payload content with various strategies
            #   - Test boundary conditions (empty, very small, very large)
            #
            # FUZZING STRATEGIES APPLIED:
            #   - BitFlip: Flip individual bits to corrupt data
            #   - ByteFlip: Flip entire bytes
            #   - Arithmetic: Add/subtract from payload bytes
            #   - InterestingValues: Insert known-bad values (0xFF, 0x00, etc.)
            #   - Havoc: Aggressive multi-mutation chaos
            #   - Splice: Combine parts from different payloads
            #
            # TIP: Set max_size to a realistic value. If the target crashes
            # on 8KB payloads, testing 1MB payloads wastes time.
        },

        # =====================================================================
        # PART 5: STRING FIELD WITH ENCODING
        # =====================================================================
        # Strings are a special case of variable-length data with encoding.

        {
            "name": "metadata_len",
            "type": "uint16",
            "is_size_field": True,
            "size_of": "metadata",

            # STRING SIZE CALCULATION:
            # For string fields, size_of uses the ENCODED byte length:
            #   metadata_len = len(metadata.encode('utf-16-le'))
            #
            # Different encodings have different byte lengths:
            #   "Hello" in UTF-8:     5 bytes
            #   "Hello" in UTF-16-LE: 10 bytes (2 bytes per char)
            #   "Hello" in UTF-32:    20 bytes (4 bytes per char)
        },
        {
            "name": "metadata",
            "type": "string",
            "max_size": 128,           # Up to 128 bytes when encoded
            "encoding": "utf-16-le",   # Little-endian UTF-16
            "default": "",

            # The `references` field is DOCUMENTATION ONLY. It tells
            # developers and UI viewers that this field has a relationship
            # with payload/payload_len (e.g., metadata describes the payload).
            "references": ["payload_len", "payload"],

            # ENCODING SHOWCASE:
            # Common encodings:
            #   - "utf-8": Variable-width (1-4 bytes per char), most common
            #   - "utf-16-le": 2 bytes per char, Windows APIs
            #   - "utf-16-be": 2 bytes per char, network protocols
            #   - "ascii": 1 byte per char, English only
            #   - "latin-1": 1 byte per char, Western European languages
            #
            # STRING FUZZING:
            # The fuzzer will generate strings with:
            #   - Special characters (@, #, $, %, etc.)
            #   - Unicode characters (emoji, CJK, RTL, etc.)
            #   - Format string patterns (%s, %x, etc.)
            #   - Null bytes and control characters
            #   - Very long strings (up to max_size)
            #
            # This finds bugs in string parsing, rendering, and storage.
        },

        # =====================================================================
        # PART 6: BEHAVIORAL FIELDS (Auto-Incrementing)
        # =====================================================================
        # Behaviors let you define fields that automatically transform across
        # messages without fuzzing.

        {
            "name": "telemetry_counter",
            "type": "uint16",
            "default": 0,
            "mutable": False,          # Don't fuzz this - it follows a pattern

            # The `behavior` dictionary defines automatic transformations.
            # Type: INCREMENT
            # Effect: Each message increments this counter by `step`
            "behavior": {
                "operation": "increment",  # Auto-increment operation
                "initial": 0,              # Start at 0
                "step": 1,                 # Add 1 each time
            },

            # HOW IT WORKS:
            # Message 1: telemetry_counter = 0
            # Message 2: telemetry_counter = 1
            # Message 3: telemetry_counter = 2
            # ... and so on
            #
            # USE CASES:
            #   - Sequence numbers (TCP seq numbers, packet IDs)
            #   - Message counters for replay attack detection
            #   - Transaction IDs that increment
            #
            # WHY mutable: False?
            # The counter needs to follow the expected sequence. Fuzzing it
            # would break the protocol state. Instead, we test that the server
            # VALIDATES sequence numbers correctly by using valid ones.
            #
            # TIP: To test sequence number validation, create separate seeds
            # with out-of-order or duplicate counters rather than fuzzing.
        },
        {
            "name": "opcode_bias",
            "type": "uint8",
            "default": 0,
            "mutable": False,
            "references": "message_type",  # This field derives from message_type

            # Type: ADD_CONSTANT
            # Effect: Always equals message_type + 3
            "behavior": {
                "operation": "add_constant",  # Add a fixed value
                "value": 0x3,                 # Add 3 to the field
            },

            # DERIVED FIELD PATTERN:
            # Some protocols have fields that are mathematical transformations
            # of other fields. For example:
            #   - opcode_bias = message_type + 3
            #   - If message_type = 0x10, then opcode_bias = 0x13
            #
            # This is common in:
            #   - Proprietary protocols with field relationships
            #   - Protocols with redundancy for error detection
            #   - Legacy protocols with quirky designs
            #
            # The framework doesn't automatically track which field to add to,
            # so `references` documents the relationship for humans.
            #
            # LIMITATION: Currently you specify the constant value, not a
            # reference to another field. For complex field relationships,
            # use the State Walker to craft messages manually.
        },
        {
            "name": "trace_cookie",
            "type": "uint32",
            "default": 0,
            "mutable": False,

            # STATEFUL PATTERN:
            # This field starts at 0 but gets populated by a response_handler.
            # After receiving a response with a trace_id, we copy it here for
            # all subsequent messages. See response_handlers below!
            #
            # This demonstrates:
            #   1. Fields that change based on server responses
            #   2. Protocol state that flows response → request → response
            #   3. Distributed tracing / request correlation patterns
        },

        # =====================================================================
        # PART 7: STATIC FOOTER
        # =====================================================================
        # Many protocols have footer markers (like \r\n for text protocols).

        {
            "name": "footer_marker",
            "type": "bytes",
            "size": 2,                 # Exactly 2 bytes
            "default": b"\r\n",        # Standard line ending
            "mutable": False,          # Don't fuzz - required for framing

            # FRAMING PATTERN:
            # The footer helps the parser know when the message ends:
            #   - Text protocols: \r\n (HTTP, SMTP, etc.)
            #   - Binary protocols: 0xDEADBEEF, 0xFF, etc.
            #   - Length-prefixed: No footer needed (length says when to stop)
            #
            # WHY mutable: False?
            # If we fuzz the footer, the parser might not recognize the message
            # end and keep reading indefinitely (timeout). While this COULD
            # find buffer over-read bugs, it's usually better to:
            #   1. Test valid messages (mutable: False)
            #   2. Separately test missing footers with custom seeds
        },
    ],

    # -------------------------------------------------------------------------
    # Seed Corpus
    # -------------------------------------------------------------------------
    # Seeds are INITIAL VALID MESSAGES that the fuzzer mutates. Think of them
    # as the "starting population" for evolutionary fuzzing.
    #
    # SEED CREATION STRATEGIES:
    #   1. Use the default values from your blocks (framework auto-generates)
    #   2. Manually craft hex bytes (shown below)
    #   3. Use the State Walker to generate and export seeds
    #   4. Capture real protocol traffic with tcpdump/Wireshark
    #   5. Use protocol libraries to generate valid messages
    #
    # BEST PRACTICES:
    #   - Start with 3-5 diverse seeds covering different message types
    #   - Each seed should exercise a different protocol feature
    #   - Seeds should be VALID messages the target accepts
    #   - Add more seeds as you find interesting behaviors
    #
    # NOTE: If you omit the "seeds" key or set it to [], the framework will
    # auto-generate seeds from your data_model default values!

    "seeds": [
        # Seed 1: Basic HANDSHAKE_REQUEST with small payload
        # Structure breakdown:
        #   SHOW                                  -> magic (4 bytes)
        #   \x01                                  -> protocol_version (1 byte)
        #   \x0B                                  -> header_len = 11 (1 byte)
        #   \xAD\xDE                              -> header_checksum = 0xDEAD little-endian (2 bytes)
        #   \x01                                  -> message_type = HANDSHAKE_REQUEST (1 byte)
        #   \x00\x00                              -> flags = 0 (2 bytes)
        #   \x00\x00\x00\x00\x00\x00\x00\x01     -> session_id = 1 (8 bytes)
        #   \x00\x00\x00\x0C                      -> payload_len = 12 (4 bytes)
        #   Hello World!                          -> payload (12 bytes)
        #   \x00\x00                              -> metadata_len = 0 (2 bytes)
        #   (empty)                               -> metadata (0 bytes)
        #   \x00                                  -> telemetry_counter = 0 (1 byte)
        #   \x00                                  -> opcode_bias = 0 (1 byte)
        #   \x00\x00\x00\x00                      -> trace_cookie = 0 (4 bytes)
        #   \r\n                                  -> footer_marker (2 bytes)
        (b"SHOW\x01\x0B\xAD\xDE\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01"
         b"\x00\x00\x00\x0C" b"Hello World!" b"\x00\x00" b"\x00\x00" b"\x00" b"\x00\x00\x00\x00" b"\r\n"),

        # Seed 2: DATA_STREAM message with different session_id
        # This demonstrates a message type used AFTER handshake.
        # Structure:
        #   message_type = 0x10 (DATA_STREAM)
        #   session_id = 0x0102030405060708 (from previous handshake)
        #   payload = "Some stream data" (16 bytes)
        (b"SHOW\x01\x0B\xAD\xDE\x10\x00\x01\x01\x02\x03\x04\x05\x06\x07\x08"
         b"\x00\x00\x00\x10" b"Some stream data" b"\x00\x00" b"\x00\x00" b"\x00" b"\x00\x00\x00\x00" b"\r\n"),

        # Seed 3: TERMINATE message with no payload
        # This tests clean shutdown and edge case of zero-length payload.
        # Structure:
        #   message_type = 0xFF (TERMINATE)
        #   session_id = 0xFFFFFFFFFFFFFFFF (all bits set)
        #   payload_len = 0 (no payload)
        (b"SHOW\x01\x0B\xAD\xDE\xFF\x00\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF"
         b"\x00\x00\x00\x00" b"\x00\x00" b"\x00\x00" b"\x00" b"\x00\x00\x00\x00" b"\r\n"),

        # TIP: To add more seeds, you can:
        #   1. Use the State Walker UI to execute transitions and export the raw hex
        #   2. Run your protocol client with logging to capture real messages
        #   3. Manually construct interesting cases (very long payloads, all flags set, etc.)
        #
        # GOOD SEEDS TO ADD:
        #   - Maximum length payload (tests buffer boundaries)
        #   - Different flag combinations (tests bitfield logic)
        #   - Each message_type value (tests all commands)
        #   - Payloads with special content (nulls, high bytes, format strings)
    ],
}


# ==============================================================================
#  SECTION 2: RESPONSE MODEL (Inbound/Response Messages)
# ==============================================================================
# The `response_model` defines the structure of RESPONSES from the target.
#
# WHY SEPARATE FROM data_model?
#   - Request and response messages often have different structures
#   - We need to PARSE responses to extract values (like session tokens)
#   - Response parsing enables stateful fuzzing (see response_handlers)
#
# HOW IT'S USED:
#   1. Target sends response bytes back to fuzzer
#   2. ProtocolParser uses response_model to parse response into fields
#   3. Response handlers can extract values and update future requests
#   4. State Walker shows parsed response fields to aid debugging
#   5. Validation oracle checks if response is logically correct
#
# WHEN TO DEFINE:
#   - Required if you use response_handlers (stateful fuzzing)
#   - Recommended if you want to debug responses in State Walker
#   - Optional if you only care about crashes (fuzzer will still work)
#
# RESPONSE MODEL DESIGN:
# Unlike data_model which describes messages we CREATE, response_model
# describes messages we RECEIVE and must PARSE. Fields here should match
# the actual server response structure.

response_model = {
    "name": "FeatureShowcaseResponses",  # Descriptive name for UI display

    # Response blocks follow the same syntax as data_model blocks, but:
    #   - They describe INBOUND data (what the server sends)
    #   - Default values are less important (we're parsing, not creating)
    #   - Focus on accurate type/size definitions for correct parsing

    "blocks": [
        # Server responses start with same magic/version for consistency
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"SHOW",  # Server echoes our protocol magic
        },
        {
            "name": "protocol_version",
            "type": "uint8",
            "default": 1,  # Server confirms version in response
        },

        # Status code indicates success/failure
        {
            "name": "status",
            "type": "uint8",
            "values": {
                0x00: "OK",         # Request succeeded
                0x01: "BUSY",       # Server busy, retry later
                0xFF: "ERROR",      # Request failed
            },
            "default": 0x00,

            # RESPONSE STATUS PATTERN:
            # Almost every protocol has some way to indicate success/failure:
            #   - HTTP: 200 OK, 404 Not Found, 500 Internal Server Error
            #   - SMTP: 250 OK, 550 Mailbox Unavailable
            #   - Custom binary: 0x00 = OK, 0xFF = ERROR
            #
            # This field is crucial for:
            #   1. Determining if the request was accepted
            #   2. Triggering response_handlers (match on status)
            #   3. Logging/debugging which requests succeeded
        },

        # Session token assigned by server after handshake
        {
            "name": "session_token",
            "type": "uint64",
            "default": 0,

            # STATEFUL SESSION PATTERN:
            # Many protocols assign session identifiers:
            #   1. Client sends HANDSHAKE_REQUEST with session_id=0
            #   2. Server responds with session_token=<random_value>
            #   3. Client uses that token in all future requests
            #
            # This enables:
            #   - Session tracking (who is this request from?)
            #   - Authentication (token proves you completed handshake)
            #   - Security (tokens are hard to guess)
            #
            # Our response_handler (below) will copy this value into the
            # session_id field of subsequent requests automatically!
        },

        # Server nonce for replay protection
        {
            "name": "server_nonce",
            "type": "uint32",
            "default": 0,

            # NONCE PATTERN:
            # A nonce (Number used ONCE) prevents replay attacks:
            #   - Server sends a random nonce in response
            #   - Client must include it in cryptographic signatures
            #   - Server rejects if nonce is reused
            #
            # Even though we're not doing crypto in this example, we
            # demonstrate the pattern for educational purposes.
        },

        # Trace ID for distributed tracing
        {
            "name": "trace_id",
            "type": "uint32",
            "default": 0,

            # DISTRIBUTED TRACING PATTERN:
            # Modern systems use trace IDs to correlate requests:
            #   - Client sends request
            #   - Server assigns trace_id and includes in response
            #   - Client includes trace_id in follow-up requests
            #   - Server logs can correlate the entire conversation
            #
            # Our response_handler copies this to trace_cookie in requests.
            #
            # REAL-WORLD EXAMPLES:
            #   - HTTP: X-Request-ID, X-Trace-Id headers
            #   - gRPC: grpc-trace-bin metadata
            #   - AWS: X-Amzn-Trace-Id
        },

        # Variable-length details field (same pattern as requests)
        {
            "name": "details_length",
            "type": "uint16",
            "is_size_field": True,
            "size_of": "details",
        },
        {
            "name": "details",
            "type": "bytes",
            "max_size": 512,  # Server can send up to 512 bytes of details
            "default": b"",

            # DETAILS FIELD PURPOSE:
            # Servers often include explanatory text:
            #   - Success: "Handshake accepted. Session token 0x..."
            #   - Error: "Invalid message type 0x99"
            #   - Status: "Processing request..."
            #
            # These help with:
            #   1. Debugging (understanding what the server did)
            #   2. Logic oracles (checking if response makes sense)
            #   3. Finding information leaks (error messages revealing internals)
        },

        # Variable-length advice field (string example)
        {
            "name": "advice_length",
            "type": "uint8",
            "is_size_field": True,
            "size_of": "advice",
        },
        {
            "name": "advice",
            "type": "string",  # Text field unlike binary 'details'
            "max_size": 64,
            "default": "",

            # ADVICE PATTERN:
            # Some protocols include hints for the client:
            #   "HANDSHAKE: Send HEARTBEAT periodically."
            #   "DATA_STREAM: Include session token in next request."
            #
            # In our feature_showcase_server.py, advice gives context-specific
            # guidance based on the current protocol state.
        },
    ],
}


# ==============================================================================
#  SECTION 3: RESPONSE HANDLERS (Stateful Protocol Behavior)
# ==============================================================================
# Response handlers define DECLARATIVE RULES for updating request fields based
# on response values. This enables STATEFUL FUZZING where the fuzzer maintains
# protocol state across multiple messages.
#
# WHAT THEY DO:
#   1. Parse the server's response using response_model
#   2. Check if response matches certain conditions ("match")
#   3. If matched, update specific request fields for NEXT message ("set_fields")
#
# EXAMPLE FLOW:
#   Client → HANDSHAKE_REQUEST (session_id=0)
#   Server → HANDSHAKE_RESPONSE (session_token=12345678)
#   [Handler activates: matches status=OK, copies session_token→session_id]
#   Client → DATA_STREAM (session_id=12345678)  ← Field updated automatically!
#
# WHY THIS MATTERS:
# Without response handlers, the fuzzer would keep sending session_id=0 for
# every message, and the server would reject them. With handlers, the fuzzer
# automatically adapts to server responses and maintains valid sessions.
#
# SYNTAX:
#   - name: Descriptive identifier for this handler
#   - match: Dictionary of conditions (ALL must be true to activate)
#   - set_fields: Dictionary of field updates to apply
#
# MATCH CONDITIONS:
#   - field_name: value       → Field must equal this value
#   - field_name: [v1, v2]    → Field must equal v1 OR v2 (any in list)
#
# SET_FIELDS:
#   - field_name: value                          → Set to constant value
#   - field_name: {"copy_from_response": "src"}  → Copy from response field

response_handlers = [
    {
        # Handler name (appears in logs and UI)
        "name": "sync_session_token",

        # WHEN TO ACTIVATE:
        # This handler activates when the response status is either:
        #   - 0x00 (OK) - Request succeeded
        #   - 0x01 (BUSY) - Server busy but acknowledged us
        #
        # It does NOT activate when status is 0xFF (ERROR).
        "match": {
            "status": [0x00, 0x01],  # List means OR (any of these values)
        },

        # WHAT TO UPDATE:
        # When this handler activates, update these fields in the NEXT request:
        "set_fields": {
            # 1. Change message type from HANDSHAKE_REQUEST to DATA_STREAM
            #    This moves the protocol forward to the next phase.
            "message_type": 0x10,  # DATA_STREAM

            # 2. Copy session_token from response to session_id in request
            #    This carries the server-assigned token into future messages.
            #
            # SYNTAX: {"copy_from_response": "field_name"}
            #    - Extracts the value of "session_token" from the parsed response
            #    - Writes that value into "session_id" field of next request
            "session_id": {"copy_from_response": "session_token"},

            # 3. Copy trace_id from response to trace_cookie in request
            #    This maintains the distributed trace across requests.
            "trace_cookie": {"copy_from_response": "trace_id"},
        },

        # HANDLER ACTIVATION EXAMPLE:
        #
        # Request #1:
        #   message_type: 0x01 (HANDSHAKE_REQUEST)
        #   session_id: 0
        #   trace_cookie: 0
        #
        # Response #1:
        #   status: 0x00 (OK)           ← Matches handler condition!
        #   session_token: 0xABCD1234
        #   trace_id: 0x5678
        #
        # [Handler activates and updates request template]
        #
        # Request #2:
        #   message_type: 0x10 (DATA_STREAM)   ← Changed by handler
        #   session_id: 0xABCD1234             ← Copied from response
        #   trace_cookie: 0x5678               ← Copied from response
        #
        # This is STATEFUL FUZZING in action!
    },

    # YOU CAN ADD MORE HANDLERS:
    # {
    #     "name": "handle_errors",
    #     "match": {"status": 0xFF},  # On ERROR response
    #     "set_fields": {
    #         "message_type": 0x01,  # Reset to HANDSHAKE_REQUEST
    #         "session_id": 0,       # Clear session
    #     },
    # },
    #
    # Multiple handlers can coexist. They're checked in order and ALL matching
    # handlers activate (so be careful with conflicting set_fields).
]


# ==============================================================================
#  SECTION 4: STATE MODEL (Multi-Step Protocol Flows)
# ==============================================================================
# The `state_model` defines a STATE MACHINE that describes valid message
# sequences for protocols with multiple phases (handshake, data, close, etc.).
#
# WHY USE STATE MODELS?
# Some protocols require messages in a specific order:
#   1. Must send HANDSHAKE_REQUEST before DATA_STREAM
#   2. Must send AUTH before any other command
#   3. Can only send TERMINATE after ESTABLISHED connection
#
# Without a state model, the fuzzer might send DATA_STREAM first, and the
# server would reject it before interesting code paths are reached.
#
# HOW IT WORKS:
#   - The fuzzer tracks the current protocol state
#   - Only sends message types valid for that state
#   - Updates state based on which transition was taken
#   - This ensures the fuzzer reaches deep code paths
#
# WHEN TO USE:
#   ✓ Protocol has distinct phases (handshake, auth, transfer, close)
#   ✓ Server rejects out-of-order messages
#   ✓ You want to test specific code paths deep in the protocol
#   ✗ Protocol is stateless (every message is independent)
#   ✗ Server accepts any message in any order
#
# COMPONENTS:
#   - initial_state: Starting state when session begins
#   - states: List of all possible states
#   - transitions: Valid state changes and what triggers them

state_model = {
    # Where does the protocol start?
    "initial_state": "UNINITIALIZED",

    # All possible states in the protocol lifecycle:
    #   UNINITIALIZED: No connection yet
    #   HANDSHAKE_SENT: Handshake sent, waiting for response
    #   ESTABLISHED: Session established, can exchange data
    #   CLOSED: Connection terminated
    "states": ["UNINITIALIZED", "HANDSHAKE_SENT", "ESTABLISHED", "CLOSED"],

    # Transitions define the edges of the state graph.
    # Each transition specifies:
    #   - from: Current state
    #   - to: Next state
    #   - message_type: What message triggers this transition
    #   - expected_response: (Optional) Expected response type
    "transitions": [
        # Transition 1: Initial handshake
        {
            "from": "UNINITIALIZED",          # Starting state
            "to": "HANDSHAKE_SENT",           # Ending state
            "message_type": "HANDSHAKE_REQUEST",  # Symbolic name from values enum
            "expected_response": "HANDSHAKE_RESPONSE",  # What we expect back

            # FLOW:
            #   State: UNINITIALIZED
            #   → Send HANDSHAKE_REQUEST
            #   → Server responds with HANDSHAKE_RESPONSE
            #   State: HANDSHAKE_SENT
            #
            # The "expected_response" is for documentation and validation.
            # If the server sends something else, it might indicate a bug.
        },

        # Transition 2: Establish session with first data message
        {
            "from": "HANDSHAKE_SENT",
            "to": "ESTABLISHED",
            "message_type": "DATA_STREAM",

            # No expected_response means we don't strictly check the response.
            # This is common when:
            #   - Response format varies
            #   - We only care that we received SOMETHING
            #   - The response_handler validates it instead
            #
            # FLOW:
            #   State: HANDSHAKE_SENT
            #   → Send DATA_STREAM (with session_token from handshake)
            #   State: ESTABLISHED
        },

        # Transition 3: Self-loop for continued data exchange
        {
            "from": "ESTABLISHED",
            "to": "ESTABLISHED",              # Same state (loop)
            "message_type": "DATA_STREAM",

            # SELF-LOOP PATTERN:
            # This allows sending multiple DATA_STREAM messages while staying
            # in the ESTABLISHED state. Common in:
            #   - Streaming protocols (send many data chunks)
            #   - Chat protocols (send many messages)
            #   - File transfer (send many blocks)
            #
            # The fuzzer can now:
            #   1. Send HANDSHAKE_REQUEST (→ HANDSHAKE_SENT)
            #   2. Send DATA_STREAM (→ ESTABLISHED)
            #   3. Send DATA_STREAM (→ ESTABLISHED) ← Loop
            #   4. Send DATA_STREAM (→ ESTABLISHED) ← Loop
            #   5. Send TERMINATE (→ CLOSED)
        },

        # Transition 4: Heartbeat (keep-alive) in established session
        {
            "from": "ESTABLISHED",
            "to": "ESTABLISHED",              # Stay in same state
            "message_type": "HEARTBEAT",

            # HEARTBEAT PATTERN:
            # Keep-alive messages prevent connection timeout:
            #   - Sent when no data is being transferred
            #   - Proves the client is still alive
            #   - Refreshes timeout timers on server
            #
            # Having this as a self-loop allows the fuzzer to send heartbeats
            # at any time during an established session.
        },

        # Transition 5: Clean shutdown from established session
        {
            "from": "ESTABLISHED",
            "to": "CLOSED",
            "message_type": "TERMINATE",

            # GRACEFUL SHUTDOWN:
            # This tests the clean disconnect path:
            #   - Client signals it's done
            #   - Server can clean up resources
            #   - Connection closes gracefully
            #
            # Contrast with fuzzing that causes crashes (abrupt disconnect).
        },

        # Transition 6: Early termination before fully establishing
        {
            "from": "HANDSHAKE_SENT",
            "to": "CLOSED",
            "message_type": "TERMINATE",

            # EDGE CASE COVERAGE:
            # What if the client decides to abort after handshake?
            # This tests:
            #   - Server cleanup of partial sessions
            #   - Race conditions (handshake response vs terminate)
            #   - Resource leak detection
            #
            # Many bugs hide in these "unusual but valid" scenarios.
        },
    ],

    # STATE MACHINE VISUALIZATION:
    #
    #                   ┌─────────────────┐
    #                   │ UNINITIALIZED   │
    #                   └────────┬────────┘
    #                            │ HANDSHAKE_REQUEST
    #                            ▼
    #                   ┌─────────────────┐
    #          ┌────────│ HANDSHAKE_SENT  │
    #          │        └────────┬────────┘
    #          │                 │ DATA_STREAM
    #          │                 ▼
    #          │        ┌─────────────────┐◄───┐
    #          │        │  ESTABLISHED    │    │ DATA_STREAM
    #          │        └────────┬────────┘    │ HEARTBEAT
    #          │                 │             │
    #          │                 │             └─ (self-loops)
    #          │                 │ TERMINATE
    #          │ TERMINATE       ▼
    #          │        ┌─────────────────┐
    #          └───────►│     CLOSED      │
    #                   └─────────────────┘
    #
    # FUZZING WITH STATE MODEL:
    # The fuzzer uses this model to:
    #   1. Generate valid message sequences (follows transitions)
    #   2. Reach deep protocol states (not just handshake)
    #   3. Test state transition logic (boundary between states)
    #   4. Find state-specific bugs (crashes only in ESTABLISHED)
    #
    # STATE WALKER UI:
    # The State Walker visualizes this graph and lets you:
    #   - Click through transitions manually
    #   - See current state and valid next moves
    #   - Verify your protocol implementation
    #   - Debug stateful behavior
}


# ==============================================================================
#  SECTION 5: RESPONSE VALIDATOR (Logic Oracle)
# ==============================================================================
# The `validate_response` function is an OPTIONAL logic oracle that checks if
# responses are LOGICALLY CORRECT, beyond just "didn't crash".
#
# WHY USE VALIDATORS?
# Crashes are only one type of bug. Others include:
#   - Logic bugs: Server returns wrong result
#   - Information leaks: Error messages reveal internal paths
#   - Inconsistent state: Session token changes unexpectedly
#   - Protocol violations: Invalid status code or missing fields
#
# Validators let you detect these as ANOMALIES in test results.
#
# HOW IT WORKS:
#   1. Target sends response bytes
#   2. Fuzzer calls validate_response(response)
#   3. If function returns False, logged as ANOMALY (not crash, but suspicious)
#   4. You can review anomalies to find logic bugs
#
# WHEN TO USE:
#   ✓ You know what valid responses should look like
#   ✓ You want to find logic bugs, not just crashes
#   ✓ Protocol has strict format requirements
#   ✗ Response format is too complex to validate simply
#   ✗ You only care about crashes (oracle is optional)
#
# IMPLEMENTATION TIPS:
#   - Keep checks simple and fast (runs on every response)
#   - Check for obvious violations (wrong magic, impossible values)
#   - Use the ProtocolParser to parse responses properly
#   - Return False only for clear violations
#   - Log what went wrong for debugging

def validate_response(response: bytes) -> bool:
    """
    Validates the logical correctness of a server response.

    This is an ORACLE function that detects non-crash bugs by checking if
    the response follows protocol rules. Called on EVERY response.

    Args:
        response: Raw response bytes from the target server

    Returns:
        True if response is logically valid
        False if response violates protocol rules (logged as ANOMALY)

    Example Checks:
        - Response has minimum required length
        - Magic bytes are correct
        - Status codes are in valid range
        - Length fields match actual data
        - Required fields are populated
    """

    import functools
    from core.engine.protocol_parser import ProtocolParser

    @functools.lru_cache(maxsize=1)
    def _response_parser() -> ProtocolParser:
        return ProtocolParser(response_model)

    try:
        fields = _response_parser().parse(response)
    except Exception:
        # Parsing failed – response not shaped like our response_model
        return False

    if fields.get("magic") != b"SHOW":
        return False

    if fields.get("protocol_version") not in (1,):
        return False

    status = fields.get("status")
    if status not in (0x00, 0x01, 0xFF):
        return False

    # On error responses, require an explanatory details payload.
    details = fields.get("details") or b""
    if status == 0xFF and len(details) == 0:
        return False

    return True


# ==============================================================================
#  HELPFUL RESOURCES
# ==============================================================================
#
# DOCUMENTATION:
#   - Framework docs: docs/ directory in repository
#   - Protocol testing guide: PROTOCOL_TESTING.md
#   - Plugin API reference: Check core/models.py for Pydantic models
#   - State machine guide: Search for StatefulFuzzingSession in core/
#
# DEBUGGING TOOLS:
#   - Plugin Explorer UI: Visualize your data_model and response_model
#   - State Walker UI: Manually test state transitions
#   - Protocol Debugger: Generate sample messages and inspect fields
#
# EXAMPLE WORKFLOWS:
#
# 1. Creating a new plugin:
#    a. Copy this file as a template
#    b. Replace data_model with your protocol structure
#    c. Create 1-3 valid seeds
#    d. Test with State Walker
#    e. Add response_model if protocol is stateful
#    f. Add state_model if protocol has phases
#
# 2. Testing a plugin:
#    a. Use Plugin Explorer to review field definitions
#    b. Use State Walker to execute transitions manually
#    c. Verify response handlers copy fields correctly
#    d. Check that state transitions work as expected
#    e. Export tested messages as additional seeds
#
# 3. Running fuzzing campaigns:
#    a. Start with seed corpus from this plugin
#    b. Monitor crashes and anomalies
#    c. Review findings in crashes/ directory
#    d. Add interesting findings to seed corpus
#    e. Iterate based on coverage feedback
#
# COMMON PITFALLS:
#   ✗ Fuzzing magic bytes (set mutable: False)
#   ✗ Missing size_of on length fields (will desync)
#   ✗ Wrong endianness (check protocol spec carefully)
#   ✗ Seeds that aren't valid messages (server rejects immediately)
#   ✗ State model too restrictive (fuzzer can't reach states)
#   ✗ State model too permissive (defeats the purpose)
#
# BEST PRACTICES:
#   ✓ Document complex fields with inline comments
#   ✓ Use descriptive names (not just "field1", "field2")
#   ✓ Group related fields with comment headers
#   ✓ Test plugin with State Walker before fuzzing
#   ✓ Start simple, add complexity incrementally
#   ✓ Capture real protocol traffic for seeds
#   ✓ Keep validators simple and fast
#
# QUESTIONS?
#   - Check the web UI documentation (Getting Started tab)
#   - Review other plugins in core/plugins/ directory
#   - Read test files in tests/ for usage examples
#   - Examine core/models.py for complete field reference
#
# Happy fuzzing! 🐛🔍
