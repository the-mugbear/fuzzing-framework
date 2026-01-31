"""
Modbus TCP Protocol Plugin - Industrial Control Systems

PURPOSE:
========
This plugin defines the Modbus TCP protocol for fuzzing industrial control
systems (ICS), SCADA systems, and PLCs (Programmable Logic Controllers).
Modbus is critical infrastructure for:

  - Manufacturing: Assembly lines, CNC machines, robotics
  - Energy: Power grids, substations, smart meters
  - Water/Wastewater: Pumps, treatment plants, distribution
  - Building Automation: HVAC, elevators, access control
  - Oil & Gas: Pipelines, refineries, drilling

SECURITY CONTEXT:
=================
Modbus was designed in 1979 with NO SECURITY features:
  - No authentication
  - No encryption
  - No integrity checking
  - Commands are accepted from any source

This makes Modbus TCP devices extremely vulnerable when exposed to
networks. Fuzzing can reveal parsing bugs that could be exploited
for denial of service or unauthorized control.

WARNING:
========
NEVER fuzz production ICS/SCADA systems without authorization.
Use isolated test environments only. Crashes in industrial systems
can cause physical damage, environmental harm, or endanger lives.

TRANSPORT:
==========
  - TCP port 502 (standard Modbus TCP)
  - Some devices use non-standard ports

PROTOCOL STRUCTURE:
===================
Modbus TCP wraps Modbus RTU frames in a TCP/IP header:

  +------------------+------------------+------------------+
  | MBAP Header      | Function Code    | Data             |
  | (7 bytes)        | (1 byte)         | (varies)         |
  +------------------+------------------+------------------+

MBAP (Modbus Application Protocol) Header:
  - Transaction ID (2 bytes): Matches requests to responses
  - Protocol ID (2 bytes): Always 0x0000 for Modbus
  - Length (2 bytes): Number of bytes following
  - Unit ID (1 byte): Slave device address

COMMON FUNCTION CODES:
======================
  Read:
    0x01 - Read Coils (discrete outputs)
    0x02 - Read Discrete Inputs
    0x03 - Read Holding Registers
    0x04 - Read Input Registers

  Write:
    0x05 - Write Single Coil
    0x06 - Write Single Register
    0x0F - Write Multiple Coils
    0x10 - Write Multiple Registers

  Diagnostic:
    0x07 - Read Exception Status
    0x08 - Diagnostics
    0x2B - Read Device Identification

COMMON VULNERABILITIES FOUND BY FUZZING:
========================================
  - Buffer overflows in quantity/address calculations
  - Integer overflows in length fields
  - Null pointer dereferences on malformed requests
  - Denial of service via repeated invalid requests
  - State corruption via out-of-range writes
  - Information disclosure via diagnostic functions

REFERENCES:
===========
  - Modbus Application Protocol Specification V1.1b3
  - Modbus Messaging on TCP/IP Implementation Guide V1.0b
  - ICS-CERT advisories for Modbus vulnerabilities
"""

__version__ = "1.0.0"
transport = "tcp"

# ==============================================================================
#  DATA MODEL - Modbus TCP Request
# ==============================================================================

data_model = {
    "name": "ModbusTCP",
    "description": "Modbus TCP/IP industrial control protocol",

    "blocks": [
        # =====================================================================
        # MBAP HEADER (7 bytes)
        # =====================================================================

        {
            "name": "transaction_id",
            "type": "uint16",
            "endian": "big",
            "default": 0x0001,

            # TRANSACTION IDENTIFIER:
            # Client-assigned ID to match requests with responses.
            # Server copies this value into the response.
            #
            # FUZZING INTEREST:
            # - Transaction ID 0x0000 may have special handling
            # - Duplicate IDs test response matching logic
            # - Maximum value (0xFFFF) tests boundary conditions
        },
        {
            "name": "protocol_id",
            "type": "uint16",
            "endian": "big",
            "default": 0x0000,
            "mutable": False,

            # PROTOCOL IDENTIFIER:
            # Always 0x0000 for Modbus protocol.
            # Non-zero values are reserved for extensions.
            #
            # FUZZING NOTE:
            # To test protocol ID validation, create separate seeds
            # with non-zero values rather than fuzzing this field.
        },
        {
            "name": "length",
            "type": "uint16",
            "endian": "big",
            "default": 6,
            "is_size_field": True,
            "size_of": ["unit_id", "function_code", "data"],

            # LENGTH:
            # Number of following bytes (Unit ID + PDU).
            # Minimum is 2 (unit_id + function_code, no data).
            # Maximum is 254 per Modbus spec.
            #
            # FUZZING INTEREST:
            # - Length mismatch with actual data tests parsing
            # - Length 0 or 1 tests minimum validation
            # - Length > 254 tests maximum validation
        },
        {
            "name": "unit_id",
            "type": "uint8",
            "default": 1,

            # UNIT IDENTIFIER:
            # Address of the target Modbus device (slave).
            # 0 = Broadcast (all devices)
            # 1-247 = Valid device addresses
            # 248-255 = Reserved
            #
            # FUZZING INTEREST:
            # - Unit ID 0 (broadcast) may enable write amplification
            # - Reserved range (248-255) tests validation
            # - Non-existent unit IDs test timeout handling
            "values": {
                0: "BROADCAST",
                255: "RESERVED",
            },
        },

        # =====================================================================
        # PDU (Protocol Data Unit)
        # =====================================================================

        {
            "name": "function_code",
            "type": "uint8",
            "default": 0x03,           # Read Holding Registers

            # FUNCTION CODE:
            # Specifies the operation to perform.
            # Codes 1-127 are standard, 128+ are exception responses.
            #
            # FUZZING TARGETS:
            # - Unimplemented function codes (many devices only support subset)
            # - Reserved codes (0, 9-14, etc.)
            # - Function codes requiring authentication
            # - Diagnostic functions (0x07, 0x08) may leak info
            "values": {
                0x01: "Read Coils",
                0x02: "Read Discrete Inputs",
                0x03: "Read Holding Registers",
                0x04: "Read Input Registers",
                0x05: "Write Single Coil",
                0x06: "Write Single Register",
                0x07: "Read Exception Status",
                0x08: "Diagnostics",
                0x0F: "Write Multiple Coils",
                0x10: "Write Multiple Registers",
                0x17: "Read/Write Multiple Registers",
                0x2B: "Read Device Identification",
            },
        },
        {
            "name": "data",
            "type": "bytes",
            "max_size": 252,           # 254 - 2 (unit_id + function_code)
            "default": b"\x00\x00\x00\x0a",  # Start addr=0, quantity=10

            # DATA:
            # Function-specific request parameters.
            # Format depends on the function code.
            #
            # READ REQUESTS (0x01-0x04):
            #   Bytes 0-1: Starting address (big-endian)
            #   Bytes 2-3: Quantity of items (big-endian)
            #
            # WRITE SINGLE COIL (0x05):
            #   Bytes 0-1: Output address
            #   Bytes 2-3: Output value (0x0000=OFF, 0xFF00=ON)
            #
            # WRITE SINGLE REGISTER (0x06):
            #   Bytes 0-1: Register address
            #   Bytes 2-3: Register value
            #
            # WRITE MULTIPLE COILS (0x0F):
            #   Bytes 0-1: Starting address
            #   Bytes 2-3: Quantity of outputs
            #   Byte 4: Byte count
            #   Bytes 5+: Output values (bit-packed)
            #
            # WRITE MULTIPLE REGISTERS (0x10):
            #   Bytes 0-1: Starting address
            #   Bytes 2-3: Quantity of registers
            #   Byte 4: Byte count
            #   Bytes 5+: Register values
            #
            # FUZZING INTEREST:
            # - Address overflow (start + quantity > 65535)
            # - Quantity limits (max 125 registers, 2000 coils)
            # - Byte count mismatch with quantity
            # - Write to read-only addresses
        },
    ],

    # =========================================================================
    # SEED CORPUS
    # =========================================================================

    "seeds": [
        # Seed 1: Read Holding Registers (Function 0x03)
        # Most common Modbus operation
        (
            b"\x00\x01"              # Transaction ID
            b"\x00\x00"              # Protocol ID (Modbus)
            b"\x00\x06"              # Length = 6
            b"\x01"                  # Unit ID = 1
            b"\x03"                  # Function: Read Holding Registers
            b"\x00\x00"              # Starting address = 0
            b"\x00\x0a"              # Quantity = 10 registers
        ),

        # Seed 2: Read Coils (Function 0x01)
        (
            b"\x00\x02"              # Transaction ID
            b"\x00\x00"              # Protocol ID
            b"\x00\x06"              # Length
            b"\x01"                  # Unit ID
            b"\x01"                  # Function: Read Coils
            b"\x00\x00"              # Starting address = 0
            b"\x00\x10"              # Quantity = 16 coils
        ),

        # Seed 3: Write Single Coil (Function 0x05)
        # Turns ON coil at address 0
        (
            b"\x00\x03"              # Transaction ID
            b"\x00\x00"              # Protocol ID
            b"\x00\x06"              # Length
            b"\x01"                  # Unit ID
            b"\x05"                  # Function: Write Single Coil
            b"\x00\x00"              # Coil address = 0
            b"\xFF\x00"              # Value = ON (0xFF00)
        ),

        # Seed 4: Write Single Register (Function 0x06)
        (
            b"\x00\x04"              # Transaction ID
            b"\x00\x00"              # Protocol ID
            b"\x00\x06"              # Length
            b"\x01"                  # Unit ID
            b"\x06"                  # Function: Write Single Register
            b"\x00\x00"              # Register address = 0
            b"\x12\x34"              # Value = 0x1234
        ),

        # Seed 5: Write Multiple Registers (Function 0x10)
        (
            b"\x00\x05"              # Transaction ID
            b"\x00\x00"              # Protocol ID
            b"\x00\x0b"              # Length = 11
            b"\x01"                  # Unit ID
            b"\x10"                  # Function: Write Multiple Registers
            b"\x00\x00"              # Starting address = 0
            b"\x00\x02"              # Quantity = 2 registers
            b"\x04"                  # Byte count = 4
            b"\xAB\xCD"              # Register 0 value
            b"\xEF\x01"              # Register 1 value
        ),

        # Seed 6: Read Input Registers (Function 0x04)
        (
            b"\x00\x06"              # Transaction ID
            b"\x00\x00"              # Protocol ID
            b"\x00\x06"              # Length
            b"\x01"                  # Unit ID
            b"\x04"                  # Function: Read Input Registers
            b"\x00\x00"              # Starting address = 0
            b"\x00\x08"              # Quantity = 8 registers
        ),

        # Seed 7: Broadcast read (Unit ID = 0)
        # Note: Broadcast is typically only valid for write operations
        (
            b"\x00\x07"              # Transaction ID
            b"\x00\x00"              # Protocol ID
            b"\x00\x06"              # Length
            b"\x00"                  # Unit ID = 0 (broadcast)
            b"\x03"                  # Function: Read Holding Registers
            b"\x00\x00"              # Starting address
            b"\x00\x01"              # Quantity = 1
        ),

        # Seed 8: Read Device Identification (Function 0x2B)
        (
            b"\x00\x08"              # Transaction ID
            b"\x00\x00"              # Protocol ID
            b"\x00\x05"              # Length = 5
            b"\x01"                  # Unit ID
            b"\x2B"                  # Function: Encapsulated Interface
            b"\x0E"                  # MEI type: Read Device ID
            b"\x01"                  # Read Device ID code: Basic
            b"\x00"                  # Object ID: Start at 0
        ),

        # Seed 9: Maximum quantity read (stress test)
        # 125 registers is the max per Modbus spec
        (
            b"\x00\x09"              # Transaction ID
            b"\x00\x00"              # Protocol ID
            b"\x00\x06"              # Length
            b"\x01"                  # Unit ID
            b"\x03"                  # Function: Read Holding Registers
            b"\x00\x00"              # Starting address
            b"\x00\x7D"              # Quantity = 125 (max)
        ),

        # Seed 10: Invalid function code
        # Tests how device handles unsupported functions
        (
            b"\x00\x0A"              # Transaction ID
            b"\x00\x00"              # Protocol ID
            b"\x00\x06"              # Length
            b"\x01"                  # Unit ID
            b"\x64"                  # Function: 100 (invalid)
            b"\x00\x00"              # Data
            b"\x00\x01"
        ),
    ],
}


# ==============================================================================
#  STATE MODEL
# ==============================================================================
# Modbus TCP is largely stateless - each request/response is independent.

state_model = {
    "initial_state": "IDLE",
    "states": ["IDLE", "REQUEST_SENT"],
    "transitions": [
        {
            "from": "IDLE",
            "to": "REQUEST_SENT",
            "message_type": "REQUEST",
        },
        {
            "from": "REQUEST_SENT",
            "to": "IDLE",
            "message_type": "REQUEST",  # Can send another request
        },
    ],
}


# ==============================================================================
#  RESPONSE VALIDATOR
# ==============================================================================

def validate_response(response: bytes) -> bool:
    """
    Validate Modbus TCP response.

    Checks:
    - Minimum length (MBAP header + function code = 8 bytes)
    - Protocol ID is 0x0000
    - Length field matches actual data
    - Function code is not an exception (0x80+) or exception is valid

    Exception Response Format:
      If high bit of function code is set (0x80+), it's an exception:
      - Original function code | 0x80
      - Exception code (1 byte): 01-0B are valid
    """
    if len(response) < 8:
        return False

    # Check protocol ID
    protocol_id = (response[2] << 8) | response[3]
    if protocol_id != 0x0000:
        return False

    # Check length field
    length = (response[4] << 8) | response[5]
    expected_len = len(response) - 6  # Total - MBAP header (minus length field)
    if length != expected_len:
        return False

    # Check for exception response
    function_code = response[7]
    if function_code >= 0x80:
        # Exception response
        if len(response) < 9:
            return False
        exception_code = response[8]
        # Valid exception codes are 1-11
        if exception_code < 1 or exception_code > 11:
            return False

    return True
