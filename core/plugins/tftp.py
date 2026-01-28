"""
TFTP Protocol Plugin - Trivial File Transfer Protocol (RFC 1350)

PURPOSE:
========
This plugin defines the TFTP protocol for fuzzing embedded device bootloaders,
network equipment, and file transfer services. TFTP is commonly used for:

  - Network device provisioning (routers, switches, access points)
  - PXE boot (network booting of computers)
  - VoIP phone configuration
  - Firmware updates for embedded devices
  - Industrial equipment configuration

SECURITY CONTEXT:
=================
TFTP has NO security features:
  - No authentication
  - No encryption
  - No access control (beyond OS file permissions)
  - Directory traversal vulnerabilities are common

Many TFTP servers have been found vulnerable to:
  - Path traversal (reading /etc/passwd, etc.)
  - Buffer overflows in filename handling
  - Denial of service via resource exhaustion

TRANSPORT:
==========
  - UDP port 69 (initial connection)
  - Server uses random high port for data transfer

PROTOCOL STRUCTURE:
===================
TFTP has 5 packet types, all starting with a 2-byte opcode:

  READ REQUEST (RRQ) - Opcode 1:
    +------------------+------------------+------------------+
    | Opcode (2 bytes) | Filename (string)| Mode (string)    |
    | 0x00 0x01        | null-terminated  | null-terminated  |
    +------------------+------------------+------------------+

  WRITE REQUEST (WRQ) - Opcode 2:
    +------------------+------------------+------------------+
    | Opcode (2 bytes) | Filename (string)| Mode (string)    |
    | 0x00 0x02        | null-terminated  | null-terminated  |
    +------------------+------------------+------------------+

  DATA - Opcode 3:
    +------------------+------------------+------------------+
    | Opcode (2 bytes) | Block # (2 bytes)| Data (0-512)     |
    | 0x00 0x03        |                  |                  |
    +------------------+------------------+------------------+

  ACK - Opcode 4:
    +------------------+------------------+
    | Opcode (2 bytes) | Block # (2 bytes)|
    | 0x00 0x04        |                  |
    +------------------+------------------+

  ERROR - Opcode 5:
    +------------------+------------------+------------------+
    | Opcode (2 bytes) | Error Code (2)   | Message (string) |
    | 0x00 0x05        |                  | null-terminated  |
    +------------------+------------------+------------------+

TRANSFER MODES:
===============
  - "netascii": ASCII text with CRLF line endings
  - "octet": Binary transfer (most common)
  - "mail": Obsolete, rarely supported

COMMON VULNERABILITIES FOUND BY FUZZING:
========================================
  - Path traversal (../../etc/passwd)
  - Buffer overflows in filename/mode handling
  - Format string bugs in error messages
  - Integer overflows in block number handling
  - Null byte injection in filenames
  - Unicode/encoding issues

REFERENCES:
===========
  - RFC 1350: The TFTP Protocol (Revision 2)
  - RFC 2347: TFTP Option Extension
  - RFC 2348: TFTP Blocksize Option
  - RFC 2349: TFTP Timeout Interval and Transfer Size Options
"""

__version__ = "1.0.0"
transport = "udp"

# ==============================================================================
#  DATA MODEL - TFTP Read Request (RRQ)
# ==============================================================================

data_model = {
    "name": "TFTP",
    "description": "Trivial File Transfer Protocol request (RFC 1350)",

    "blocks": [
        # =====================================================================
        # OPCODE (2 bytes)
        # =====================================================================

        {
            "name": "opcode",
            "type": "uint16",
            "endian": "big",
            "default": 1,              # 1 = RRQ (Read Request)

            # OPCODE:
            # Identifies the type of TFTP packet.
            #
            # Valid opcodes:
            #   1 = RRQ (Read Request)
            #   2 = WRQ (Write Request)
            #   3 = DATA
            #   4 = ACK
            #   5 = ERROR
            #   6 = OACK (Option Acknowledgment, RFC 2347)
            #
            # FUZZING INTEREST:
            # - Invalid opcodes (0, 7+) test error handling
            # - Opcode 2 (WRQ) may allow unauthorized writes
            # - Opcode 6 (OACK) without prior RRQ tests state handling
            "values": {
                1: "RRQ",
                2: "WRQ",
                3: "DATA",
                4: "ACK",
                5: "ERROR",
                6: "OACK",
            },
        },

        # =====================================================================
        # FILENAME (Variable length, null-terminated)
        # =====================================================================

        {
            "name": "filename",
            "type": "bytes",
            "max_size": 512,
            "default": b"test.txt\x00",

            # FILENAME:
            # The file to read or write, null-terminated.
            #
            # PATH TRAVERSAL VULNERABILITIES:
            # Many TFTP servers are vulnerable to path traversal:
            #   - "../../../etc/passwd" - Read system files
            #   - "/etc/shadow" - Absolute path
            #   - "..\\..\\windows\\system32\\config\\sam" - Windows
            #
            # FUZZING TARGETS:
            # - Very long filenames (buffer overflow)
            # - Null bytes in middle of filename
            # - Special characters (*, ?, |, etc.)
            # - Unicode characters
            # - Path separators (/, \, %2f, %5c)
            # - Empty filename (just null terminator)
            # - Missing null terminator
        },

        # =====================================================================
        # MODE (Variable length, null-terminated)
        # =====================================================================

        {
            "name": "mode",
            "type": "bytes",
            "max_size": 32,
            "default": b"octet\x00",

            # MODE:
            # Transfer mode, null-terminated.
            #
            # Valid modes:
            #   "netascii" - ASCII text transfer
            #   "octet" - Binary transfer (most common)
            #   "mail" - Obsolete
            #
            # FUZZING TARGETS:
            # - Invalid mode strings
            # - Very long mode strings
            # - Mixed case (some servers are case-sensitive)
            # - Empty mode
            # - Missing null terminator
            #
            # Note: Mode is case-insensitive per RFC.
        },

        # =====================================================================
        # OPTIONS (RFC 2347 extension, optional)
        # =====================================================================

        {
            "name": "options",
            "type": "bytes",
            "max_size": 256,
            "default": b"",

            # OPTIONS:
            # RFC 2347 TFTP Option Extension allows additional parameters
            # as null-terminated key-value pairs after the mode.
            #
            # Common options:
            #   "blksize" + "\0" + size + "\0" - Block size (RFC 2348)
            #   "tsize" + "\0" + "0" + "\0" - Transfer size query
            #   "timeout" + "\0" + seconds + "\0" - Timeout (RFC 2349)
            #
            # FUZZING TARGETS:
            # - Invalid option names
            # - Invalid option values (non-numeric for blksize)
            # - Very large blksize values (65535+)
            # - Negative or zero timeout
            # - Duplicate options
            # - Options without values
        },
    ],

    # =========================================================================
    # SEED CORPUS
    # =========================================================================

    "seeds": [
        # Seed 1: Basic RRQ for test file in binary mode
        (
            b"\x00\x01"              # Opcode: RRQ
            b"test.txt\x00"          # Filename
            b"octet\x00"             # Mode: binary
        ),

        # Seed 2: RRQ with netascii mode
        (
            b"\x00\x01"              # Opcode: RRQ
            b"readme.txt\x00"        # Filename
            b"netascii\x00"          # Mode: ASCII
        ),

        # Seed 3: WRQ (Write Request)
        (
            b"\x00\x02"              # Opcode: WRQ
            b"upload.bin\x00"        # Filename
            b"octet\x00"             # Mode: binary
        ),

        # Seed 4: RRQ with blksize option (RFC 2348)
        (
            b"\x00\x01"              # Opcode: RRQ
            b"large.bin\x00"         # Filename
            b"octet\x00"             # Mode
            b"blksize\x00"           # Option name
            b"1428\x00"              # Block size (MTU-friendly)
        ),

        # Seed 5: RRQ with tsize option (RFC 2349)
        (
            b"\x00\x01"              # Opcode: RRQ
            b"firmware.bin\x00"      # Filename
            b"octet\x00"             # Mode
            b"tsize\x00"             # Option name
            b"0\x00"                 # Size query
        ),

        # Seed 6: Path traversal attempt (for security testing)
        (
            b"\x00\x01"              # Opcode: RRQ
            b"../../../etc/passwd\x00"  # Traversal path
            b"octet\x00"             # Mode
        ),

        # Seed 7: RRQ with multiple options
        (
            b"\x00\x01"              # Opcode: RRQ
            b"config.cfg\x00"        # Filename
            b"octet\x00"             # Mode
            b"blksize\x00"           # Option 1
            b"512\x00"
            b"timeout\x00"           # Option 2
            b"5\x00"
        ),

        # Seed 8: Absolute path (some servers allow this)
        (
            b"\x00\x01"              # Opcode: RRQ
            b"/tftpboot/pxelinux.0\x00"  # Absolute path
            b"octet\x00"             # Mode
        ),

        # Seed 9: Empty filename (edge case)
        (
            b"\x00\x01"              # Opcode: RRQ
            b"\x00"                  # Empty filename
            b"octet\x00"             # Mode
        ),

        # Seed 10: Very long filename (boundary testing)
        (
            b"\x00\x01"              # Opcode: RRQ
            + b"A" * 200 + b".txt\x00"  # Long filename
            b"octet\x00"             # Mode
        ),
    ],
}


# ==============================================================================
#  STATE MODEL - TFTP Transfer States
# ==============================================================================

state_model = {
    "initial_state": "IDLE",
    "states": ["IDLE", "RRQ_SENT", "WRQ_SENT", "TRANSFERRING", "COMPLETE"],
    "transitions": [
        {
            "from": "IDLE",
            "to": "RRQ_SENT",
            "message_type": "RRQ",
        },
        {
            "from": "IDLE",
            "to": "WRQ_SENT",
            "message_type": "WRQ",
        },
        {
            "from": "RRQ_SENT",
            "to": "TRANSFERRING",
            "message_type": "DATA",
            "expected_response": "DATA",
        },
        {
            "from": "WRQ_SENT",
            "to": "TRANSFERRING",
            "message_type": "DATA",
            "expected_response": "ACK",
        },
        {
            "from": "TRANSFERRING",
            "to": "TRANSFERRING",
            "message_type": "DATA",
        },
        {
            "from": "TRANSFERRING",
            "to": "COMPLETE",
            "message_type": "ACK",
        },
    ],
}


# ==============================================================================
#  RESPONSE VALIDATOR
# ==============================================================================

def validate_response(response: bytes) -> bool:
    """
    Validate TFTP response.

    Valid responses to RRQ:
    - DATA packet (opcode 3): file contents
    - ERROR packet (opcode 5): error message
    - OACK packet (opcode 6): option acknowledgment

    Checks:
    - Minimum length (4 bytes for ACK/ERROR header)
    - Valid opcode
    - Valid error code (if ERROR packet)
    """
    if len(response) < 4:
        return False

    opcode = (response[0] << 8) | response[1]

    # Valid response opcodes: DATA(3), ACK(4), ERROR(5), OACK(6)
    if opcode not in (3, 4, 5, 6):
        return False

    if opcode == 5:  # ERROR
        # Check error code is valid (0-7)
        error_code = (response[2] << 8) | response[3]
        if error_code > 7:
            return False

    if opcode == 3:  # DATA
        # Must have at least opcode (2) + block# (2) = 4 bytes
        # Data can be 0-512 bytes
        if len(response) > 4 + 512:
            return False

    return True
