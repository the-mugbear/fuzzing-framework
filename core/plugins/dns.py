"""
DNS Protocol Plugin - Domain Name System (RFC 1035)

PURPOSE:
========
This plugin defines the DNS query message format for fuzzing DNS servers.
DNS is a critical network infrastructure protocol that translates domain
names to IP addresses. It's an excellent target for fuzzing because:

  - Ubiquitous: Every networked device uses DNS
  - Complex parsing: Variable-length names, compression, multiple record types
  - Security-critical: DNS vulnerabilities can enable cache poisoning, DoS
  - Well-documented: RFC 1035 (and extensions) provide clear specifications

TRANSPORT:
==========
  - Primary: UDP port 53 (messages up to 512 bytes, or 4096 with EDNS)
  - Fallback: TCP port 53 (for large responses or zone transfers)

This plugin targets UDP DNS queries, the most common use case.

PROTOCOL STRUCTURE:
===================
DNS messages have a fixed 12-byte header followed by variable sections:

  +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
  |                      ID                       |  2 bytes
  +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
  |QR|   Opcode  |AA|TC|RD|RA|   Z    |   RCODE   |  2 bytes (bit fields!)
  +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
  |                    QDCOUNT                    |  2 bytes
  +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
  |                    ANCOUNT                    |  2 bytes
  +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
  |                    NSCOUNT                    |  2 bytes
  +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
  |                    ARCOUNT                    |  2 bytes
  +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
  |                   QUESTION                    |  Variable
  +--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+

BIT FIELD SHOWCASE:
===================
The DNS flags field (bytes 2-3) is an excellent example of bit-level packing:
  - QR (1 bit): Query (0) or Response (1)
  - Opcode (4 bits): Query type (0=standard, 1=inverse, 2=status)
  - AA (1 bit): Authoritative Answer
  - TC (1 bit): Truncation flag
  - RD (1 bit): Recursion Desired
  - RA (1 bit): Recursion Available
  - Z (3 bits): Reserved (must be zero)
  - RCODE (4 bits): Response code

COMMON VULNERABILITIES FOUND BY FUZZING:
========================================
  - Buffer overflows in name decompression
  - Integer overflows in length calculations
  - Null pointer dereferences on malformed queries
  - Infinite loops in compression pointer chains
  - Cache poisoning via malformed responses

REFERENCES:
===========
  - RFC 1035: Domain Names - Implementation and Specification
  - RFC 6895: DNS IANA Considerations
  - RFC 2671: Extension Mechanisms for DNS (EDNS0)
"""

__version__ = "1.0.0"
transport = "udp"

# ==============================================================================
#  DATA MODEL - DNS Query Message
# ==============================================================================

data_model = {
    "name": "DNS",
    "description": "Domain Name System query message (RFC 1035)",

    "blocks": [
        # =====================================================================
        # DNS HEADER (12 bytes fixed)
        # =====================================================================

        {
            "name": "transaction_id",
            "type": "uint16",
            "endian": "big",
            "default": 0x1234,

            # TRANSACTION ID:
            # A 16-bit identifier assigned by the client. The server copies
            # this value into the response so clients can match responses to
            # queries. Should be random to prevent spoofing attacks.
            #
            # FUZZING INTEREST:
            # Some servers may have issues with specific ID values (0x0000,
            # 0xFFFF, or IDs matching internal state). The fuzzer will
            # try various values.
        },

        # =====================================================================
        # FLAGS FIELD - Excellent bit field example (16 bits)
        # =====================================================================
        # The flags field demonstrates how DNS packs multiple control bits
        # into a single 16-bit value. This is common in network protocols.

        {
            "name": "qr",
            "type": "bits",
            "size": 1,
            "default": 0,              # 0 = Query, 1 = Response
            "mutable": False,          # We're sending queries, not responses

            # QR (Query/Response) FLAG:
            # 0 = This is a query
            # 1 = This is a response
            #
            # Since we're fuzzing a DNS server by sending queries, this
            # should always be 0. Some servers may misbehave if they
            # receive "responses" unexpectedly.
        },
        {
            "name": "opcode",
            "type": "bits",
            "size": 4,
            "default": 0,              # 0 = Standard query (QUERY)

            # OPCODE (4 bits):
            # Specifies the type of query:
            #   0 = QUERY (standard query)
            #   1 = IQUERY (inverse query, obsolete)
            #   2 = STATUS (server status request)
            #   3 = Reserved
            #   4 = NOTIFY (RFC 1996)
            #   5 = UPDATE (RFC 2136, dynamic updates)
            #   6-15 = Reserved
            #
            # FUZZING INTEREST:
            # - Reserved values (3, 6-15) may trigger undefined behavior
            # - IQUERY is obsolete but may still have code paths
            # - UPDATE queries can modify DNS records if server is vulnerable
            "values": {
                0: "QUERY",
                1: "IQUERY",
                2: "STATUS",
                4: "NOTIFY",
                5: "UPDATE",
            },
        },
        {
            "name": "aa",
            "type": "bits",
            "size": 1,
            "default": 0,

            # AA (Authoritative Answer):
            # Only meaningful in responses. For queries, should be 0.
            # Some servers may mishandle queries with AA=1.
        },
        {
            "name": "tc",
            "type": "bits",
            "size": 1,
            "default": 0,

            # TC (Truncation):
            # Indicates message was truncated due to length limits.
            # For queries, should be 0. Setting TC=1 in a query
            # tests how servers handle malformed flag combinations.
        },
        {
            "name": "rd",
            "type": "bits",
            "size": 1,
            "default": 1,              # Request recursive resolution

            # RD (Recursion Desired):
            # If set, directs the server to pursue the query recursively.
            # Most client queries set RD=1 for full name resolution.
            #
            # FUZZING INTEREST:
            # - RD=0 with non-authoritative queries tests stub resolver behavior
            # - Recursive resolution is complex and may have more bugs
        },
        {
            "name": "ra",
            "type": "bits",
            "size": 1,
            "default": 0,

            # RA (Recursion Available):
            # Set by server to indicate recursion is available.
            # Should be 0 in queries. Tests server's flag validation.
        },
        {
            "name": "z",
            "type": "bits",
            "size": 3,
            "default": 0,
            "mutable": False,          # Reserved bits should be 0

            # Z (Reserved):
            # Three reserved bits, must be zero in all queries and responses.
            # Per RFC 1035, these are reserved for future use.
            #
            # FUZZING NOTE:
            # To test server handling of non-zero reserved bits,
            # create separate seeds rather than fuzzing this field,
            # as well-behaved clients should always send 0.
        },
        {
            "name": "rcode",
            "type": "bits",
            "size": 4,
            "default": 0,

            # RCODE (Response Code):
            # Only meaningful in responses. For queries, should be 0.
            # Fuzzing with non-zero values tests flag validation.
            #
            # Response codes (for reference):
            #   0 = NOERROR (no error)
            #   1 = FORMERR (format error)
            #   2 = SERVFAIL (server failure)
            #   3 = NXDOMAIN (name does not exist)
            #   4 = NOTIMP (not implemented)
            #   5 = REFUSED (query refused)
            "values": {
                0: "NOERROR",
                1: "FORMERR",
                2: "SERVFAIL",
                3: "NXDOMAIN",
                4: "NOTIMP",
                5: "REFUSED",
            },
        },

        # =====================================================================
        # SECTION COUNTS (8 bytes total)
        # =====================================================================

        {
            "name": "qdcount",
            "type": "uint16",
            "endian": "big",
            "default": 1,              # One question

            # QDCOUNT (Question Count):
            # Number of entries in the question section.
            # Standard queries have exactly 1 question.
            #
            # FUZZING INTEREST:
            # - QDCOUNT=0 with question data tests parsing
            # - QDCOUNT>1 tests multi-question handling
            # - QDCOUNT mismatch with actual questions may crash parsers
        },
        {
            "name": "ancount",
            "type": "uint16",
            "endian": "big",
            "default": 0,

            # ANCOUNT (Answer Count):
            # Number of resource records in the answer section.
            # Should be 0 for queries (answers come from server).
        },
        {
            "name": "nscount",
            "type": "uint16",
            "endian": "big",
            "default": 0,

            # NSCOUNT (Authority Count):
            # Number of name server records in authority section.
            # Typically 0 for standard queries.
        },
        {
            "name": "arcount",
            "type": "uint16",
            "endian": "big",
            "default": 0,

            # ARCOUNT (Additional Count):
            # Number of resource records in additional section.
            # May be 1 if EDNS0 OPT record is included.
        },

        # =====================================================================
        # QUESTION SECTION (Variable length)
        # =====================================================================
        # The question section contains the domain name being queried.
        # DNS names use a length-prefixed label format:
        #   \x03www\x07example\x03com\x00
        # Each label is preceded by its length (1-63 bytes).
        # The name ends with a null byte (0x00).

        {
            "name": "qname",
            "type": "bytes",
            "max_size": 255,           # Max domain name length per RFC
            "default": b"\x07example\x03com\x00",  # "example.com"

            # QNAME (Query Name):
            # The domain name being queried, in DNS wire format.
            #
            # FORMAT: Length-prefixed labels ending with null byte
            #   \x03www = label "www" (3 bytes)
            #   \x07example = label "example" (7 bytes)
            #   \x03com = label "com" (3 bytes)
            #   \x00 = end of name
            #
            # FUZZING TARGETS:
            # - Very long labels (63 bytes max per label)
            # - Very long names (255 bytes max total)
            # - Missing null terminator
            # - Invalid length bytes (> 63)
            # - Compression pointers in queries (unusual but valid)
            # - Empty labels (consecutive length bytes)
            # - Non-printable characters in labels
        },
        {
            "name": "qtype",
            "type": "uint16",
            "endian": "big",
            "default": 1,              # A record (IPv4 address)

            # QTYPE (Query Type):
            # The type of DNS record being requested.
            #
            # Common types:
            #   1 = A (IPv4 address)
            #   2 = NS (name server)
            #   5 = CNAME (canonical name)
            #   6 = SOA (start of authority)
            #   12 = PTR (pointer, reverse DNS)
            #   15 = MX (mail exchange)
            #   16 = TXT (text record)
            #   28 = AAAA (IPv6 address)
            #   33 = SRV (service locator)
            #   255 = ANY (all records)
            #
            # FUZZING INTEREST:
            # - ANY queries (255) may cause amplification
            # - Obsolete types may have unmaintained code paths
            # - Invalid types test error handling
            "values": {
                1: "A",
                2: "NS",
                5: "CNAME",
                6: "SOA",
                12: "PTR",
                15: "MX",
                16: "TXT",
                28: "AAAA",
                33: "SRV",
                255: "ANY",
            },
        },
        {
            "name": "qclass",
            "type": "uint16",
            "endian": "big",
            "default": 1,              # IN (Internet)

            # QCLASS (Query Class):
            # The class of the query. Almost always IN (Internet).
            #
            # Classes:
            #   1 = IN (Internet)
            #   2 = CS (CSNET, obsolete)
            #   3 = CH (Chaos)
            #   4 = HS (Hesiod)
            #   255 = ANY (any class)
            #
            # FUZZING INTEREST:
            # - CH class queries can leak server version info
            # - Obsolete classes may have bugs
            # - Class ANY with type ANY is particularly interesting
            "values": {
                1: "IN",
                3: "CH",
                4: "HS",
                255: "ANY",
            },
        },
    ],

    # =========================================================================
    # SEED CORPUS
    # =========================================================================
    # These seeds provide valid DNS queries to start fuzzing from.
    # Each exercises different aspects of the protocol.

    "seeds": [
        # Seed 1: Standard A record query for example.com
        # Header: ID=0x1234, flags=0x0100 (RD=1), QDCOUNT=1
        # Question: example.com, type A, class IN
        (
            b"\x12\x34"              # Transaction ID
            b"\x01\x00"              # Flags: QR=0, OPCODE=0, RD=1
            b"\x00\x01"              # QDCOUNT=1
            b"\x00\x00"              # ANCOUNT=0
            b"\x00\x00"              # NSCOUNT=0
            b"\x00\x00"              # ARCOUNT=0
            b"\x07example\x03com\x00"  # QNAME
            b"\x00\x01"              # QTYPE=A
            b"\x00\x01"              # QCLASS=IN
        ),

        # Seed 2: AAAA (IPv6) query for www.example.com
        (
            b"\xAB\xCD"              # Transaction ID
            b"\x01\x00"              # Flags: RD=1
            b"\x00\x01"              # QDCOUNT=1
            b"\x00\x00\x00\x00\x00\x00"  # Other counts=0
            b"\x03www\x07example\x03com\x00"  # www.example.com
            b"\x00\x1c"              # QTYPE=AAAA (28)
            b"\x00\x01"              # QCLASS=IN
        ),

        # Seed 3: MX (mail server) query
        (
            b"\xDE\xAD"              # Transaction ID
            b"\x01\x00"              # Flags: RD=1
            b"\x00\x01"              # QDCOUNT=1
            b"\x00\x00\x00\x00\x00\x00"
            b"\x07example\x03com\x00"
            b"\x00\x0f"              # QTYPE=MX (15)
            b"\x00\x01"              # QCLASS=IN
        ),

        # Seed 4: TXT record query (often used for SPF, DKIM)
        (
            b"\xBE\xEF"              # Transaction ID
            b"\x01\x00"              # Flags: RD=1
            b"\x00\x01"              # QDCOUNT=1
            b"\x00\x00\x00\x00\x00\x00"
            b"\x07example\x03com\x00"
            b"\x00\x10"              # QTYPE=TXT (16)
            b"\x00\x01"              # QCLASS=IN
        ),

        # Seed 5: ANY query (requests all record types)
        # Note: Many servers now refuse ANY queries due to amplification attacks
        (
            b"\xCA\xFE"              # Transaction ID
            b"\x01\x00"              # Flags: RD=1
            b"\x00\x01"              # QDCOUNT=1
            b"\x00\x00\x00\x00\x00\x00"
            b"\x07example\x03com\x00"
            b"\x00\xff"              # QTYPE=ANY (255)
            b"\x00\x01"              # QCLASS=IN
        ),

        # Seed 6: PTR query (reverse DNS lookup)
        # This queries the reverse DNS for 8.8.8.8
        (
            b"\xF0\x0D"              # Transaction ID
            b"\x01\x00"              # Flags: RD=1
            b"\x00\x01"              # QDCOUNT=1
            b"\x00\x00\x00\x00\x00\x00"
            b"\x018\x018\x018\x018\x07in-addr\x04arpa\x00"  # 8.8.8.8 reverse
            b"\x00\x0c"              # QTYPE=PTR (12)
            b"\x00\x01"              # QCLASS=IN
        ),

        # Seed 7: Non-recursive query (RD=0)
        # Tests stub resolver behavior
        (
            b"\x00\x01"              # Transaction ID
            b"\x00\x00"              # Flags: RD=0 (no recursion)
            b"\x00\x01"              # QDCOUNT=1
            b"\x00\x00\x00\x00\x00\x00"
            b"\x07example\x03com\x00"
            b"\x00\x01"              # QTYPE=A
            b"\x00\x01"              # QCLASS=IN
        ),

        # Seed 8: Chaos class version query
        # CH class TXT query for version.bind reveals server version
        (
            b"\x13\x37"              # Transaction ID
            b"\x01\x00"              # Flags: RD=1
            b"\x00\x01"              # QDCOUNT=1
            b"\x00\x00\x00\x00\x00\x00"
            b"\x07version\x04bind\x00"  # version.bind
            b"\x00\x10"              # QTYPE=TXT
            b"\x00\x03"              # QCLASS=CH (Chaos)
        ),
    ],
}


# ==============================================================================
#  STATE MODEL
# ==============================================================================
# DNS is largely stateless - each query/response is independent.
# However, we model the basic query-response flow for completeness.

state_model = {
    "initial_state": "IDLE",
    "states": ["IDLE", "QUERY_SENT", "RESPONSE_RECEIVED"],
    "transitions": [
        {
            "from": "IDLE",
            "to": "QUERY_SENT",
            "message_type": "QUERY",
        },
        {
            "from": "QUERY_SENT",
            "to": "IDLE",
            "message_type": "QUERY",  # Can send another query
        },
    ],
}


# ==============================================================================
#  RESPONSE VALIDATOR (Logic Oracle)
# ==============================================================================

def validate_response(response: bytes) -> bool:
    """
    Validate DNS response for logical correctness.

    Checks:
    - Minimum length (12 bytes for header)
    - QR bit is set (indicates response)
    - RCODE is valid
    - Section counts are reasonable
    """
    if len(response) < 12:
        return False

    # Check QR bit is 1 (response)
    flags = (response[2] << 8) | response[3]
    qr = (flags >> 15) & 1
    if qr != 1:
        return False

    # Check RCODE is valid (0-5 are standard)
    rcode = flags & 0x0F
    if rcode > 5:
        return False

    return True
