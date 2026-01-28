"""
NTP Protocol Plugin - Network Time Protocol (RFC 5905)

PURPOSE:
========
This plugin defines the NTP protocol for fuzzing time synchronization servers.
NTP is critical infrastructure that affects:

  - Certificate validation (TLS/SSL relies on accurate time)
  - Logging and forensics (timestamps for event correlation)
  - Financial transactions (trading systems, audit trails)
  - Authentication systems (Kerberos, TOTP, certificate expiry)
  - Distributed systems (consensus algorithms, cache expiry)

SECURITY CONTEXT:
=================
NTP has been the source of significant vulnerabilities:
  - Amplification attacks (monlist command, CVE-2013-5211)
  - Remote code execution in ntpd (CVE-2014-9295)
  - Timestamp manipulation for security bypass
  - Denial of service via malformed packets

TRANSPORT:
==========
  - UDP port 123 (primary)

PROTOCOL STRUCTURE:
===================
NTP uses a 48-byte packet format (minimum) with bit fields in the first byte:

  +------------------+------------------+------------------+------------------+
  | LI|VN|Mode       | Stratum          | Poll             | Precision        |
  | (8 bits)         | (8 bits)         | (8 bits)         | (8 bits)         |
  +------------------+------------------+------------------+------------------+
  |                        Root Delay (32 bits)                               |
  +------------------+------------------+------------------+------------------+
  |                     Root Dispersion (32 bits)                             |
  +------------------+------------------+------------------+------------------+
  |                     Reference ID (32 bits)                                |
  +------------------+------------------+------------------+------------------+
  |                                                                           |
  |                   Reference Timestamp (64 bits)                           |
  |                                                                           |
  +------------------+------------------+------------------+------------------+
  |                                                                           |
  |                    Origin Timestamp (64 bits)                             |
  |                                                                           |
  +------------------+------------------+------------------+------------------+
  |                                                                           |
  |                    Receive Timestamp (64 bits)                            |
  |                                                                           |
  +------------------+------------------+------------------+------------------+
  |                                                                           |
  |                   Transmit Timestamp (64 bits)                            |
  |                                                                           |
  +------------------+------------------+------------------+------------------+

BIT FIELD SHOWCASE:
===================
The first byte contains three packed fields:
  - LI (Leap Indicator): 2 bits
  - VN (Version Number): 3 bits
  - Mode: 3 bits

This is an excellent example of how network protocols pack multiple
small values into single bytes for efficiency.

COMMON VULNERABILITIES FOUND BY FUZZING:
========================================
  - Buffer overflows in extension parsing
  - Integer overflows in timestamp calculations
  - Denial of service via malformed mode 7 packets
  - Information disclosure via control messages
  - Amplification via monlist/peer queries

REFERENCES:
===========
  - RFC 5905: Network Time Protocol Version 4
  - RFC 4330: Simple NTP (SNTP) Version 4
  - NTP Pool Project
  - CVE database for NTP vulnerabilities
"""

__version__ = "1.0.0"
transport = "udp"

# ==============================================================================
#  DATA MODEL - NTP Client Request
# ==============================================================================

data_model = {
    "name": "NTP",
    "description": "Network Time Protocol v4 client request (RFC 5905)",

    "blocks": [
        # =====================================================================
        # FIRST BYTE - Bit Fields (LI, VN, Mode)
        # =====================================================================
        # The first byte of NTP packets is a perfect example of bit packing.
        # Three distinct fields are packed into 8 bits.

        {
            "name": "leap_indicator",
            "type": "bits",
            "size": 2,
            "default": 0,              # 0 = no warning

            # LEAP INDICATOR (LI) - 2 bits:
            # Warning of an impending leap second.
            #
            # Values:
            #   0 = No warning
            #   1 = Last minute of day has 61 seconds (leap second insert)
            #   2 = Last minute of day has 59 seconds (leap second delete)
            #   3 = Clock unsynchronized (alarm condition)
            #
            # FUZZING INTEREST:
            # - LI=3 in a request is unusual (client claiming unsync)
            # - Some servers may behave differently based on client LI
            "values": {
                0: "NO_WARNING",
                1: "LAST_61",
                2: "LAST_59",
                3: "UNSYNC",
            },
        },
        {
            "name": "version",
            "type": "bits",
            "size": 3,
            "default": 4,              # NTP version 4

            # VERSION NUMBER (VN) - 3 bits:
            # NTP protocol version.
            #
            # Values:
            #   1-2 = Obsolete versions
            #   3 = NTPv3 (RFC 1305)
            #   4 = NTPv4 (RFC 5905, current)
            #   5-7 = Reserved/undefined
            #
            # FUZZING INTEREST:
            # - Version 0 is invalid
            # - Versions 5-7 are undefined
            # - Old versions may have different code paths
            "values": {
                3: "NTPv3",
                4: "NTPv4",
            },
        },
        {
            "name": "mode",
            "type": "bits",
            "size": 3,
            "default": 3,              # 3 = Client

            # MODE - 3 bits:
            # NTP operational mode.
            #
            # Values:
            #   0 = Reserved
            #   1 = Symmetric Active
            #   2 = Symmetric Passive
            #   3 = Client
            #   4 = Server
            #   5 = Broadcast
            #   6 = NTP Control Message
            #   7 = Reserved for private use
            #
            # FUZZING INTEREST:
            # - Mode 3 (Client) is normal for requests
            # - Mode 6 (Control) can query server state
            # - Mode 7 (Private) was used for monlist attacks
            # - Mode 0 is reserved and should be rejected
            "values": {
                0: "RESERVED",
                1: "SYMMETRIC_ACTIVE",
                2: "SYMMETRIC_PASSIVE",
                3: "CLIENT",
                4: "SERVER",
                5: "BROADCAST",
                6: "CONTROL",
                7: "PRIVATE",
            },
        },

        # =====================================================================
        # REMAINING HEADER FIELDS
        # =====================================================================

        {
            "name": "stratum",
            "type": "uint8",
            "default": 0,              # 0 = unspecified (client request)

            # STRATUM:
            # Distance from the reference clock.
            #
            # Values:
            #   0 = Unspecified or invalid
            #   1 = Primary server (directly connected to reference)
            #   2-15 = Secondary servers (synchronized to stratum-1)
            #   16 = Unsynchronized
            #   17-255 = Reserved
            #
            # FUZZING INTEREST:
            # - Stratum 0 in client request is normal
            # - Stratum 16+ values test validation
            "values": {
                0: "UNSPECIFIED",
                1: "PRIMARY",
                16: "UNSYNCHRONIZED",
            },
        },
        {
            "name": "poll",
            "type": "uint8",
            "default": 0,              # 2^0 = 1 second minimum

            # POLL INTERVAL:
            # Exponent of maximum interval between messages (2^poll seconds).
            #
            # Typical values: 4-17 (16 seconds to 36 hours)
            # Client requests often use 0 (immediate response wanted).
            #
            # FUZZING INTEREST:
            # - Very large poll values test timeout handling
            # - Negative effective values (if signed) test math
        },
        {
            "name": "precision",
            "type": "int8",             # Signed!
            "default": -6,              # 2^-6 = ~15.6 milliseconds

            # PRECISION:
            # Precision of the system clock (2^precision seconds).
            # Typically -6 to -20 for modern systems.
            #
            # Note: This is signed, allowing very precise clocks
            # (e.g., -20 = 2^-20 = ~1 microsecond).
            #
            # FUZZING INTEREST:
            # - Extreme positive values (2^127 seconds = huge)
            # - Extreme negative values (-128)
        },

        # =====================================================================
        # TIME QUALITY FIELDS (8 bytes)
        # =====================================================================

        {
            "name": "root_delay",
            "type": "uint32",
            "endian": "big",
            "default": 0,

            # ROOT DELAY:
            # Total round-trip delay to the reference clock.
            # Fixed-point: upper 16 bits = seconds, lower 16 bits = fraction.
            #
            # For client requests, this is typically 0.
        },
        {
            "name": "root_dispersion",
            "type": "uint32",
            "endian": "big",
            "default": 0,

            # ROOT DISPERSION:
            # Total dispersion to the reference clock.
            # Represents maximum error due to the frequency tolerance
            # of all clocks in the synchronization subnet.
            #
            # For client requests, this is typically 0.
        },
        {
            "name": "reference_id",
            "type": "bytes",
            "size": 4,
            "default": b"\x00\x00\x00\x00",

            # REFERENCE ID:
            # Identifies the reference source.
            #
            # Interpretation depends on stratum:
            # - Stratum 0-1: 4-character ASCII code (GPS, PPS, WWV, etc.)
            # - Stratum 2+: IPv4 address of reference server
            #              (or first 4 bytes of MD5 hash for IPv6)
            #
            # FUZZING INTEREST:
            # - ASCII codes vs IP addresses
            # - Special codes (LOCL, INIT, etc.)
        },

        # =====================================================================
        # TIMESTAMPS (32 bytes total, 4 x 64-bit)
        # =====================================================================
        # NTP uses 64-bit timestamps: 32 bits for seconds since 1900,
        # 32 bits for fractional seconds.

        {
            "name": "reference_timestamp",
            "type": "uint64",
            "endian": "big",
            "default": 0,

            # REFERENCE TIMESTAMP:
            # Time when the system clock was last set or corrected.
            # For client requests, typically 0.
        },
        {
            "name": "origin_timestamp",
            "type": "uint64",
            "endian": "big",
            "default": 0,

            # ORIGIN TIMESTAMP:
            # Time at which the request departed the client.
            # The server copies this to the response for round-trip calculation.
            #
            # For initial client request, this is 0.
            # For subsequent requests, this is the transmit time of the
            # previous request.
        },
        {
            "name": "receive_timestamp",
            "type": "uint64",
            "endian": "big",
            "default": 0,

            # RECEIVE TIMESTAMP:
            # Time at which the request arrived at the server.
            # For client requests, this is 0 (server fills it in).
        },
        {
            "name": "transmit_timestamp",
            "type": "uint64",
            "endian": "big",
            "default": 0,

            # TRANSMIT TIMESTAMP:
            # Time at which the packet departed.
            # Client should set this to current time for accurate sync.
            #
            # FUZZING INTEREST:
            # - Future timestamps (time in the future)
            # - Past timestamps (before NTP epoch 1900)
            # - Maximum value (year 2036 problem)
        },
    ],

    # =========================================================================
    # SEED CORPUS
    # =========================================================================

    "seeds": [
        # Seed 1: Standard NTPv4 client request
        # LI=0, VN=4, Mode=3 -> 0x23 (0b00100011)
        (
            b"\x23"                  # LI=0, VN=4, Mode=3
            b"\x00"                  # Stratum=0
            b"\x00"                  # Poll=0
            b"\xfa"                  # Precision=-6
            b"\x00\x00\x00\x00"      # Root delay
            b"\x00\x00\x00\x00"      # Root dispersion
            b"\x00\x00\x00\x00"      # Reference ID
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Reference timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Origin timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Receive timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Transmit timestamp
        ),

        # Seed 2: NTPv3 client request (for compatibility testing)
        # LI=0, VN=3, Mode=3 -> 0x1B (0b00011011)
        (
            b"\x1B"                  # LI=0, VN=3, Mode=3
            b"\x00\x00\xfa"          # Stratum, Poll, Precision
            b"\x00\x00\x00\x00"      # Root delay
            b"\x00\x00\x00\x00"      # Root dispersion
            b"\x00\x00\x00\x00"      # Reference ID
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Reference timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Origin timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Receive timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Transmit timestamp
        ),

        # Seed 3: Request with non-zero transmit timestamp
        (
            b"\x23"                  # LI=0, VN=4, Mode=3
            b"\x00\x00\xfa"          # Stratum, Poll, Precision
            b"\x00\x00\x00\x00"      # Root delay
            b"\x00\x00\x00\x00"      # Root dispersion
            b"\x00\x00\x00\x00"      # Reference ID
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Reference timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Origin timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Receive timestamp
            b"\xE3\x5B\x67\x89\x12\x34\x56\x78"  # Transmit: ~2020 timestamp
        ),

        # Seed 4: Symmetric active mode (peer-to-peer)
        # LI=0, VN=4, Mode=1 -> 0x21 (0b00100001)
        (
            b"\x21"                  # LI=0, VN=4, Mode=1 (Symmetric Active)
            b"\x00\x00\xfa"          # Stratum, Poll, Precision
            b"\x00\x00\x00\x00"      # Root delay
            b"\x00\x00\x00\x00"      # Root dispersion
            b"\x00\x00\x00\x00"      # Reference ID
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Reference timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Origin timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Receive timestamp
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Transmit timestamp
        ),

        # Seed 5: Broadcast mode
        # LI=0, VN=4, Mode=5 -> 0x25 (0b00100101)
        (
            b"\x25"                  # LI=0, VN=4, Mode=5 (Broadcast)
            b"\x01\x00\xfa"          # Stratum=1 (primary), Poll, Precision
            b"\x00\x00\x00\x00"      # Root delay
            b"\x00\x00\x00\x00"      # Root dispersion
            b"GPS\x00"               # Reference ID = GPS
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
        ),

        # Seed 6: Leap second warning
        # LI=1, VN=4, Mode=3 -> 0x63 (0b01100011)
        (
            b"\x63"                  # LI=1 (61 seconds), VN=4, Mode=3
            b"\x00\x00\xfa"          # Stratum, Poll, Precision
            b"\x00\x00\x00\x00"      # Root delay
            b"\x00\x00\x00\x00"      # Root dispersion
            b"\x00\x00\x00\x00"      # Reference ID
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
        ),

        # Seed 7: Unsynchronized clock indicator
        # LI=3, VN=4, Mode=3 -> 0xE3 (0b11100011)
        (
            b"\xE3"                  # LI=3 (unsync), VN=4, Mode=3
            b"\x10\x00\xfa"          # Stratum=16 (unsync)
            b"\x00\x00\x00\x00"      # Root delay
            b"\x00\x00\x00\x00"      # Root dispersion
            b"INIT"                  # Reference ID = INIT (initializing)
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
        ),

        # Seed 8: Reserved mode (Mode=0)
        # This tests how servers handle invalid mode
        (
            b"\x20"                  # LI=0, VN=4, Mode=0 (RESERVED)
            b"\x00\x00\xfa"
            b"\x00\x00\x00\x00"
            b"\x00\x00\x00\x00"
            b"\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
        ),
    ],
}


# ==============================================================================
#  STATE MODEL
# ==============================================================================
# NTP is largely stateless for basic client-server operation.

state_model = {
    "initial_state": "IDLE",
    "states": ["IDLE", "POLLING"],
    "transitions": [
        {
            "from": "IDLE",
            "to": "POLLING",
            "message_type": "CLIENT",
        },
        {
            "from": "POLLING",
            "to": "IDLE",
            "message_type": "CLIENT",  # Can poll again
        },
    ],
}


# ==============================================================================
#  RESPONSE VALIDATOR
# ==============================================================================

def validate_response(response: bytes) -> bool:
    """
    Validate NTP server response.

    Checks:
    - Minimum length (48 bytes)
    - Mode is 4 (Server) or 5 (Broadcast)
    - Version is 3 or 4
    - LI is valid (0-3)
    - Stratum is reasonable (0-16)
    """
    if len(response) < 48:
        return False

    first_byte = response[0]
    li = (first_byte >> 6) & 0x03
    vn = (first_byte >> 3) & 0x07
    mode = first_byte & 0x07

    # Check leap indicator is valid (0-3)
    if li > 3:
        return False

    # Check version is 3 or 4
    if vn not in (3, 4):
        return False

    # Check mode is server (4) or broadcast (5) or symmetric passive (2)
    if mode not in (2, 4, 5):
        return False

    # Check stratum is reasonable
    stratum = response[1]
    if stratum > 16:
        return False

    return True
