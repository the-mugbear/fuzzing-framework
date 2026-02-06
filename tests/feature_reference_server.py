#!/usr/bin/env python3
"""
Feature Reference Protocol Test Server
======================================

A purpose-built test server for the feature_reference protocol plugin that:
1. Properly parses and responds to protocol messages (not just echo)
2. Implements the state machine (UNINITIALIZED → HANDSHAKE_SENT → ESTABLISHED → CLOSED)
3. Contains INTENTIONAL VULNERABILITIES for training users to find bugs
4. Provides clear, colorful logging for understanding protocol flow

INTENTIONAL VULNERABILITIES (for training):
==========================================
Find these bugs using the fuzzer! Each has a difficulty rating.

★☆☆☆☆ EASY:
  - CVE-FAKE-001: Buffer overflow when payload > 2048 bytes
  - CVE-FAKE-002: Magic value 0xDEADBEEF in session_id bypasses auth

★★☆☆☆ MEDIUM:
  - CVE-FAKE-003: Integer overflow in payload_len * 2 calculation
  - CVE-FAKE-004: Payload containing "CRASH" triggers null pointer

★★★☆☆ HARD:
  - CVE-FAKE-005: Format string bug when payload contains %s%s%s%n
  - CVE-FAKE-006: Use-after-free when DATA_STREAM sent after TERMINATE

★★★★☆ EXPERT:
  - CVE-FAKE-007: Race condition with fragmented=1 and priority=3
  - CVE-FAKE-008: Memory disclosure when encrypted=1 but no key set

★★★★★ MASTER:
  - CVE-FAKE-009: State confusion with simultaneous HEARTBEAT+TERMINATE flags
  - CVE-FAKE-010: Heap corruption with specific bit field combination

USAGE:
======
    python tests/feature_reference_server.py [--host HOST] [--port PORT]

    Default: 0.0.0.0:9999

Part of the Proprietary Protocol Fuzzer framework.
"""

import argparse
import os
import random
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Optional, Tuple


# =============================================================================
# ANSI Color Codes for Terminal Output
# =============================================================================

class Colors:
    """ANSI escape codes for colorful terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"

    @classmethod
    def disable(cls):
        """Disable colors (for non-TTY output)."""
        for attr in dir(cls):
            if not attr.startswith('_') and attr.isupper():
                setattr(cls, attr, "")


# =============================================================================
# Protocol Constants
# =============================================================================

MAGIC = b"SHOW"
PROTOCOL_VERSION = 1

class MessageType(IntEnum):
    """Message types defined in the protocol."""
    HANDSHAKE_REQUEST = 0x01
    HANDSHAKE_RESPONSE = 0x02
    DATA_STREAM = 0x10
    DATA_ACK = 0x11
    HEARTBEAT = 0xFE
    TERMINATE = 0xFF


class Status(IntEnum):
    """Response status codes."""
    OK = 0x00
    BUSY = 0x01
    ERROR = 0xFF


class SessionState(IntEnum):
    """Session state machine states."""
    UNINITIALIZED = 0
    HANDSHAKE_SENT = 1
    ESTABLISHED = 2
    CLOSED = 3


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class ParsedRequest:
    """Parsed request message from client."""
    magic: bytes = b""
    protocol_version: int = 0
    header_len: int = 0
    header_checksum: int = 0
    message_type: int = 0
    flags: int = 0
    session_id: int = 0

    # Bit fields (byte 1)
    encrypted_bit: int = 0
    compressed_bit: int = 0
    fragmented_bit: int = 0
    priority: int = 0
    reserved_bits: int = 0

    # Bit fields (bytes 2-3)
    sequence_number: int = 0
    channel_id: int = 0

    # Bit fields (bytes 4-5)
    qos_level: int = 0
    ecn_bits: int = 0
    ack_flag: int = 0
    more_fragments: int = 0
    fragment_offset: int = 0

    # Variable fields
    payload_len: int = 0
    payload: bytes = b""
    metadata_len: int = 0
    metadata: bytes = b""

    # Behavior fields
    telemetry_counter: int = 0
    opcode_bias: int = 0
    trace_cookie: int = 0
    terminator: bytes = b""

    # Parsing metadata
    raw_data: bytes = b""
    parse_error: Optional[str] = None


@dataclass
class Session:
    """Client session state."""
    session_id: int = 0
    state: SessionState = SessionState.UNINITIALIZED
    token: int = 0
    nonce: int = 0
    trace_id: int = 0
    message_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    # For vulnerability simulation
    freed: bool = False  # CVE-FAKE-006: Use-after-free flag


# =============================================================================
# Protocol Parser
# =============================================================================

class ProtocolParser:
    """Parser for feature_reference protocol messages."""

    # Minimum message size (header fields before variable-length data)
    # magic(4) + version(1) + header_len(1) + checksum(2) + msg_type(1) +
    # flags(2) + session_id(8) + bit_fields(5) + payload_len(2) + metadata_len(2) +
    # telemetry(2) + opcode(1) + trace(4) + terminator(2) = 37 bytes minimum
    MIN_MESSAGE_SIZE = 37

    @classmethod
    def parse(cls, data: bytes) -> ParsedRequest:
        """Parse a raw message into structured fields."""
        req = ParsedRequest(raw_data=data)

        if len(data) < cls.MIN_MESSAGE_SIZE:
            req.parse_error = f"Message too short: {len(data)} < {cls.MIN_MESSAGE_SIZE}"
            return req

        try:
            offset = 0

            # Magic (4 bytes)
            req.magic = data[offset:offset+4]
            offset += 4

            # Protocol version (1 byte)
            req.protocol_version = data[offset]
            offset += 1

            # Header length (1 byte)
            req.header_len = data[offset]
            offset += 1

            # Header checksum (2 bytes, little-endian)
            req.header_checksum = struct.unpack('<H', data[offset:offset+2])[0]
            offset += 2

            # Message type (1 byte)
            req.message_type = data[offset]
            offset += 1

            # Flags (2 bytes, big-endian)
            req.flags = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2

            # Session ID (8 bytes)
            req.session_id = struct.unpack('>Q', data[offset:offset+8])[0]
            offset += 8

            # Bit fields byte 1: encrypted(1) + compressed(1) + fragmented(1) + priority(2) + reserved(3)
            bf1 = data[offset]
            req.encrypted_bit = (bf1 >> 7) & 0x01
            req.compressed_bit = (bf1 >> 6) & 0x01
            req.fragmented_bit = (bf1 >> 5) & 0x01
            req.priority = (bf1 >> 3) & 0x03
            req.reserved_bits = bf1 & 0x07
            offset += 1

            # Bit fields bytes 2-3: sequence_number(12) + channel_id(4)
            bf23 = struct.unpack('>H', data[offset:offset+2])[0]
            req.sequence_number = (bf23 >> 4) & 0x0FFF
            req.channel_id = bf23 & 0x0F
            offset += 2

            # Bit fields bytes 4-5: qos(3) + ecn(2) + ack(1) + more(1) + frag_off(8)
            bf45 = struct.unpack('>H', data[offset:offset+2])[0]
            req.qos_level = (bf45 >> 13) & 0x07
            req.ecn_bits = (bf45 >> 11) & 0x03
            req.ack_flag = (bf45 >> 10) & 0x01
            req.more_fragments = (bf45 >> 9) & 0x01
            req.fragment_offset = bf45 & 0x01FF
            offset += 2

            # Payload length (2 bytes)
            req.payload_len = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2

            # Payload (variable)
            if offset + req.payload_len > len(data):
                req.parse_error = f"Payload extends beyond message: {offset + req.payload_len} > {len(data)}"
                return req
            req.payload = data[offset:offset+req.payload_len]
            offset += req.payload_len

            # Metadata length (2 bytes)
            if offset + 2 > len(data):
                req.parse_error = "Missing metadata length"
                return req
            req.metadata_len = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2

            # Metadata (variable)
            if offset + req.metadata_len > len(data):
                req.parse_error = f"Metadata extends beyond message"
                return req
            req.metadata = data[offset:offset+req.metadata_len]
            offset += req.metadata_len

            # Telemetry counter (2 bytes)
            if offset + 2 > len(data):
                req.parse_error = "Missing telemetry counter"
                return req
            req.telemetry_counter = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2

            # Opcode bias (1 byte)
            if offset + 1 > len(data):
                req.parse_error = "Missing opcode bias"
                return req
            req.opcode_bias = data[offset]
            offset += 1

            # Trace cookie (4 bytes)
            if offset + 4 > len(data):
                req.parse_error = "Missing trace cookie"
                return req
            req.trace_cookie = struct.unpack('>I', data[offset:offset+4])[0]
            offset += 4

            # Terminator (2 bytes)
            if offset + 2 <= len(data):
                req.terminator = data[offset:offset+2]

        except Exception as e:
            req.parse_error = f"Parse exception: {str(e)}"

        return req


# =============================================================================
# Response Builder
# =============================================================================

class ResponseBuilder:
    """Builder for feature_reference protocol responses."""

    @classmethod
    def build(
        cls,
        status: Status,
        session_token: int = 0,
        server_nonce: int = 0,
        trace_id: int = 0,
        details: bytes = b"",
        advice: str = ""
    ) -> bytes:
        """Build a response message."""
        advice_bytes = advice.encode('utf-8')

        response = bytearray()

        # Magic (4 bytes)
        response.extend(MAGIC)

        # Protocol version (1 byte)
        response.append(PROTOCOL_VERSION)

        # Status (1 byte)
        response.append(status)

        # Session token (8 bytes)
        response.extend(struct.pack('>Q', session_token))

        # Server nonce (4 bytes)
        response.extend(struct.pack('>I', server_nonce))

        # Trace ID (4 bytes)
        response.extend(struct.pack('>I', trace_id))

        # Details length + details
        response.extend(struct.pack('>H', len(details)))
        response.extend(details)

        # Advice length + advice
        response.append(len(advice_bytes))
        response.extend(advice_bytes)

        return bytes(response)


# =============================================================================
# Vulnerability Checker
# =============================================================================

class VulnerabilityChecker:
    """
    Checks for intentional vulnerability triggers.

    Each vulnerability simulates a real bug pattern that fuzzing should find.
    """

    @classmethod
    def check_all(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        Check all vulnerabilities. Returns (vuln_id, description) if triggered.
        """
        checks = [
            cls._check_buffer_overflow,
            cls._check_auth_bypass,
            cls._check_integer_overflow,
            cls._check_null_pointer,
            cls._check_format_string,
            cls._check_use_after_free,
            cls._check_race_condition,
            cls._check_memory_disclosure,
            cls._check_state_confusion,
            cls._check_heap_corruption,
        ]

        for check in checks:
            result = check(req, session)
            if result:
                return result

        return None

    @classmethod
    def _check_buffer_overflow(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-001: Buffer overflow when payload > 2048 bytes
        Difficulty: ★☆☆☆☆ EASY
        """
        if req.payload_len > 2048:
            return ("CVE-FAKE-001",
                    f"BUFFER OVERFLOW! Payload size {req.payload_len} exceeds 2048 byte buffer")
        return None

    @classmethod
    def _check_auth_bypass(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-002: Magic session_id 0xDEADBEEF bypasses authentication
        Difficulty: ★☆☆☆☆ EASY
        """
        if req.session_id == 0xDEADBEEF:
            return ("CVE-FAKE-002",
                    "AUTH BYPASS! Magic session_id 0xDEADBEEF accepted without handshake")
        return None

    @classmethod
    def _check_integer_overflow(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-003: Integer overflow when payload_len approaches 32768
        Difficulty: ★★☆☆☆ MEDIUM
        """
        # Simulate: size = payload_len * 2 (for UTF-16 conversion)
        # If payload_len > 32767, multiplication overflows signed 16-bit
        if req.payload_len >= 32768:
            return ("CVE-FAKE-003",
                    f"INTEGER OVERFLOW! payload_len {req.payload_len} * 2 overflows 16-bit signed")
        return None

    @classmethod
    def _check_null_pointer(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-004: Payload containing "CRASH" triggers null pointer dereference
        Difficulty: ★★☆☆☆ MEDIUM
        """
        if b"CRASH" in req.payload:
            return ("CVE-FAKE-004",
                    "NULL POINTER DEREFERENCE! Payload contains forbidden 'CRASH' sequence")
        return None

    @classmethod
    def _check_format_string(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-005: Format string bug when payload contains %s%s%s%n
        Difficulty: ★★★☆☆ HARD
        """
        dangerous_patterns = [b"%s%s%s", b"%n", b"%x%x%x%x"]
        for pattern in dangerous_patterns:
            if pattern in req.payload:
                return ("CVE-FAKE-005",
                        f"FORMAT STRING BUG! Payload contains unescaped format specifier")
        return None

    @classmethod
    def _check_use_after_free(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-006: Use-after-free when processing after session marked freed
        Difficulty: ★★★☆☆ HARD
        """
        if session.freed and req.message_type == MessageType.DATA_STREAM:
            return ("CVE-FAKE-006",
                    "USE-AFTER-FREE! DATA_STREAM processed on freed session object")
        return None

    @classmethod
    def _check_race_condition(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-007: Race condition with fragmented=1 and priority=3 (URGENT)
        Difficulty: ★★★★☆ EXPERT
        """
        if req.fragmented_bit == 1 and req.priority == 3 and req.more_fragments == 1:
            return ("CVE-FAKE-007",
                    "RACE CONDITION! Urgent fragmented message with more_fragments triggers race")
        return None

    @classmethod
    def _check_memory_disclosure(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-008: Memory disclosure when encrypted=1 but session has no key
        Difficulty: ★★★★☆ EXPERT
        """
        if req.encrypted_bit == 1 and session.state == SessionState.UNINITIALIZED:
            return ("CVE-FAKE-008",
                    "MEMORY DISCLOSURE! Encrypted flag set but no session key established")
        return None

    @classmethod
    def _check_state_confusion(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-009: State confusion with specific flag + message type combo
        Difficulty: ★★★★★ MASTER
        """
        # Heartbeat with ack_flag=1 and qos_level=7 causes state confusion
        if (req.message_type == MessageType.HEARTBEAT and
            req.ack_flag == 1 and
            req.qos_level == 7):
            return ("CVE-FAKE-009",
                    "STATE CONFUSION! HEARTBEAT with ack=1 and qos=7 corrupts session state")
        return None

    @classmethod
    def _check_heap_corruption(cls, req: ParsedRequest, session: Session) -> Optional[Tuple[str, str]]:
        """
        CVE-FAKE-010: Heap corruption with specific bit field combination
        Difficulty: ★★★★★ MASTER
        """
        # All bit flags set + specific sequence + channel triggers heap corruption
        if (req.encrypted_bit == 1 and
            req.compressed_bit == 1 and
            req.fragmented_bit == 1 and
            req.sequence_number == 0xFFF and
            req.channel_id == 0xF and
            req.ecn_bits == 3):
            return ("CVE-FAKE-010",
                    "HEAP CORRUPTION! Specific bit field combination corrupts heap metadata")
        return None


# =============================================================================
# Logger
# =============================================================================

class Logger:
    """Colorful, structured logging for protocol events."""

    def __init__(self, color_enabled: bool = True):
        if not color_enabled:
            Colors.disable()

    def banner(self):
        """Print startup banner."""
        print(f"\n{Colors.BLUE}{'='*70}{Colors.RESET}")
        print(f"{Colors.MAGENTA}{Colors.BOLD}  Feature Reference Protocol Test Server{Colors.RESET}")
        print(f"{Colors.CYAN}  Training server with intentional vulnerabilities{Colors.RESET}")
        print(f"{Colors.BLUE}{'='*70}{Colors.RESET}\n")

    def info(self, msg: str):
        print(f"{Colors.BLUE}[INFO]{Colors.RESET}    {msg}")

    def success(self, msg: str):
        print(f"{Colors.GREEN}[OK]{Colors.RESET}      {msg}")

    def warning(self, msg: str):
        print(f"{Colors.YELLOW}[WARN]{Colors.RESET}    {msg}")

    def error(self, msg: str):
        print(f"{Colors.RED}[ERROR]{Colors.RESET}   {msg}")

    def crash(self, vuln_id: str, description: str):
        """Log a triggered vulnerability (simulated crash)."""
        print(f"\n{Colors.BG_RED}{Colors.WHITE}{Colors.BOLD}")
        print(f"  {'!'*66}  ")
        print(f"  !! VULNERABILITY TRIGGERED: {vuln_id:40} !!  ")
        print(f"  {'!'*66}  ")
        print(f"{Colors.RESET}")
        print(f"{Colors.RED}{Colors.BOLD}  {description}{Colors.RESET}\n")

    def connection(self, addr: Tuple[str, int], action: str):
        """Log connection events."""
        print(f"{Colors.CYAN}[CONN]{Colors.RESET}    {addr[0]}:{addr[1]} - {action}")

    def request(self, req: ParsedRequest):
        """Log a parsed request with details."""
        msg_name = self._msg_type_name(req.message_type)

        print(f"\n{Colors.MAGENTA}{'─'*70}{Colors.RESET}")
        print(f"{Colors.MAGENTA}[REQUEST]{Colors.RESET} {Colors.BOLD}{msg_name}{Colors.RESET}")
        print(f"{Colors.MAGENTA}{'─'*70}{Colors.RESET}")

        # Header info
        print(f"  {Colors.DIM}Magic:{Colors.RESET}        {req.magic!r}")
        print(f"  {Colors.DIM}Version:{Colors.RESET}      {req.protocol_version}")
        print(f"  {Colors.DIM}Header Len:{Colors.RESET}   {req.header_len}")
        print(f"  {Colors.DIM}Checksum:{Colors.RESET}     0x{req.header_checksum:04X}")
        print(f"  {Colors.DIM}Session ID:{Colors.RESET}   0x{req.session_id:016X}")

        # Bit fields
        print(f"  {Colors.DIM}Bit Fields:{Colors.RESET}")
        print(f"    encrypted={req.encrypted_bit} compressed={req.compressed_bit} "
              f"fragmented={req.fragmented_bit} priority={req.priority}")
        print(f"    seq={req.sequence_number} channel={req.channel_id} "
              f"qos={req.qos_level} ecn={req.ecn_bits}")
        print(f"    ack={req.ack_flag} more_frags={req.more_fragments} "
              f"frag_off={req.fragment_offset}")

        # Payload
        if req.payload:
            preview = req.payload[:32]
            hex_preview = preview.hex()
            if len(req.payload) > 32:
                hex_preview += "..."
            print(f"  {Colors.DIM}Payload:{Colors.RESET}      {req.payload_len} bytes: {hex_preview}")
        else:
            print(f"  {Colors.DIM}Payload:{Colors.RESET}      (empty)")

        # Metadata
        if req.metadata:
            print(f"  {Colors.DIM}Metadata:{Colors.RESET}     {req.metadata_len} bytes")

        # Behavior fields
        print(f"  {Colors.DIM}Telemetry:{Colors.RESET}    {req.telemetry_counter}")
        print(f"  {Colors.DIM}Trace:{Colors.RESET}        0x{req.trace_cookie:08X}")

        if req.parse_error:
            print(f"  {Colors.RED}Parse Error:{Colors.RESET} {req.parse_error}")

    def response(self, status: Status, token: int, details: str, advice: str):
        """Log the response being sent."""
        status_color = Colors.GREEN if status == Status.OK else (
            Colors.YELLOW if status == Status.BUSY else Colors.RED
        )
        status_name = ["OK", "BUSY", "ERROR"][status] if status <= 2 else f"0x{status:02X}"

        print(f"\n{Colors.GREEN}{'─'*70}{Colors.RESET}")
        print(f"{Colors.GREEN}[RESPONSE]{Colors.RESET} Status: {status_color}{status_name}{Colors.RESET}")
        print(f"{Colors.GREEN}{'─'*70}{Colors.RESET}")
        print(f"  {Colors.DIM}Token:{Colors.RESET}   0x{token:016X}")
        if details:
            print(f"  {Colors.DIM}Details:{Colors.RESET} {details[:60]}{'...' if len(details) > 60 else ''}")
        if advice:
            print(f"  {Colors.DIM}Advice:{Colors.RESET}  {advice}")
        print()

    def state_transition(self, old_state: SessionState, new_state: SessionState, trigger: str):
        """Log a state machine transition."""
        print(f"{Colors.YELLOW}[STATE]{Colors.RESET}   {old_state.name} → {new_state.name} (via {trigger})")

    def _msg_type_name(self, msg_type: int) -> str:
        """Get human-readable message type name."""
        names = {
            0x01: "HANDSHAKE_REQUEST",
            0x02: "HANDSHAKE_RESPONSE",
            0x10: "DATA_STREAM",
            0x11: "DATA_ACK",
            0xFE: "HEARTBEAT",
            0xFF: "TERMINATE",
        }
        return names.get(msg_type, f"UNKNOWN(0x{msg_type:02X})")


# =============================================================================
# Protocol Handler
# =============================================================================

class ProtocolHandler:
    """Handles protocol logic and state machine transitions."""

    def __init__(self, logger: Logger):
        self.logger = logger
        self.sessions: Dict[int, Session] = {}
        self._session_counter = 0

    def handle(self, req: ParsedRequest, client_addr: Tuple[str, int]) -> bytes:
        """
        Handle a request and return a response.

        This implements the full protocol state machine with vulnerability checks.
        """
        # Get or create session
        session = self._get_or_create_session(req.session_id, client_addr)

        # Check for vulnerabilities FIRST (before normal processing)
        vuln = VulnerabilityChecker.check_all(req, session)
        if vuln:
            self.logger.crash(vuln[0], vuln[1])
            # Return error response with vulnerability info
            return ResponseBuilder.build(
                status=Status.ERROR,
                session_token=session.token,
                trace_id=session.trace_id,
                details=f"CRASH: {vuln[0]}".encode(),
                advice=vuln[1][:64]
            )

        # Validate magic
        if req.magic != MAGIC:
            self.logger.warning(f"Invalid magic: {req.magic!r}")
            return ResponseBuilder.build(
                status=Status.ERROR,
                details=b"Invalid magic bytes",
                advice="Expected: SHOW"
            )

        # Validate protocol version
        if req.protocol_version != PROTOCOL_VERSION:
            self.logger.warning(f"Invalid version: {req.protocol_version}")
            return ResponseBuilder.build(
                status=Status.ERROR,
                details=f"Unsupported version {req.protocol_version}".encode(),
                advice=f"Use version {PROTOCOL_VERSION}"
            )

        # Route by message type
        if req.message_type == MessageType.HANDSHAKE_REQUEST:
            return self._handle_handshake(req, session)
        elif req.message_type == MessageType.DATA_STREAM:
            return self._handle_data_stream(req, session)
        elif req.message_type == MessageType.HEARTBEAT:
            return self._handle_heartbeat(req, session)
        elif req.message_type == MessageType.TERMINATE:
            return self._handle_terminate(req, session)
        else:
            self.logger.warning(f"Unknown message type: 0x{req.message_type:02X}")
            return ResponseBuilder.build(
                status=Status.ERROR,
                session_token=session.token,
                details=f"Unknown message type 0x{req.message_type:02X}".encode(),
                advice="Valid types: 0x01, 0x10, 0xFE, 0xFF"
            )

    def _get_or_create_session(self, session_id: int, client_addr: Tuple[str, int]) -> Session:
        """Get existing session or create new one."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.last_activity = time.time()
            session.message_count += 1
            return session

        # Create new session
        self._session_counter += 1
        token = random.randint(1, 0xFFFFFFFFFFFFFFFF)
        nonce = random.randint(1, 0xFFFFFFFF)
        trace = random.randint(1, 0xFFFFFFFF)

        session = Session(
            session_id=self._session_counter,
            token=token,
            nonce=nonce,
            trace_id=trace,
        )

        # Don't store yet - only store after successful handshake
        return session

    def _handle_handshake(self, req: ParsedRequest, session: Session) -> bytes:
        """Handle HANDSHAKE_REQUEST message."""
        old_state = session.state

        if session.state != SessionState.UNINITIALIZED:
            self.logger.warning(f"Handshake in invalid state: {session.state.name}")
            return ResponseBuilder.build(
                status=Status.ERROR,
                session_token=session.token,
                details=b"Already handshaked",
                advice="Send DATA_STREAM or TERMINATE"
            )

        # Successful handshake
        session.state = SessionState.HANDSHAKE_SENT
        self.sessions[session.token] = session

        self.logger.state_transition(old_state, session.state, "HANDSHAKE_REQUEST")

        return ResponseBuilder.build(
            status=Status.OK,
            session_token=session.token,
            server_nonce=session.nonce,
            trace_id=session.trace_id,
            details=b"Handshake accepted",
            advice="Send DATA_STREAM to establish session"
        )

    def _handle_data_stream(self, req: ParsedRequest, session: Session) -> bytes:
        """Handle DATA_STREAM message."""
        old_state = session.state

        # Validate session state
        if session.state == SessionState.UNINITIALIZED:
            self.logger.warning("DATA_STREAM without handshake")
            return ResponseBuilder.build(
                status=Status.ERROR,
                details=b"No active session",
                advice="Send HANDSHAKE_REQUEST first"
            )

        if session.state == SessionState.CLOSED:
            self.logger.warning("DATA_STREAM on closed session")
            return ResponseBuilder.build(
                status=Status.ERROR,
                session_token=session.token,
                details=b"Session closed",
                advice="Start new session with HANDSHAKE_REQUEST"
            )

        # Validate session token
        if req.session_id != session.token and req.session_id != 0:
            self.logger.warning(f"Token mismatch: got 0x{req.session_id:X}, expected 0x{session.token:X}")
            return ResponseBuilder.build(
                status=Status.ERROR,
                session_token=session.token,
                details=b"Invalid session token",
                advice="Use token from HANDSHAKE_RESPONSE"
            )

        # Transition to ESTABLISHED if coming from HANDSHAKE_SENT
        if session.state == SessionState.HANDSHAKE_SENT:
            session.state = SessionState.ESTABLISHED
            self.logger.state_transition(old_state, session.state, "DATA_STREAM")

        # Check ECN for congestion simulation
        if req.ecn_bits == 3:  # CE (Congestion Experienced)
            return ResponseBuilder.build(
                status=Status.BUSY,
                session_token=session.token,
                server_nonce=session.nonce,
                trace_id=session.trace_id,
                details=b"Server congested",
                advice="Reduce sending rate"
            )

        # Process payload
        payload_info = f"Received {req.payload_len} bytes"
        if req.compressed_bit:
            payload_info += " (compressed)"
        if req.encrypted_bit:
            payload_info += " (encrypted)"

        return ResponseBuilder.build(
            status=Status.OK,
            session_token=session.token,
            server_nonce=session.nonce,
            trace_id=session.trace_id,
            details=payload_info.encode(),
            advice="Continue sending or TERMINATE"
        )

    def _handle_heartbeat(self, req: ParsedRequest, session: Session) -> bytes:
        """Handle HEARTBEAT message."""
        if session.state != SessionState.ESTABLISHED:
            self.logger.warning(f"HEARTBEAT in state {session.state.name}")
            return ResponseBuilder.build(
                status=Status.ERROR,
                session_token=session.token,
                details=b"Session not established",
                advice="Complete handshake first"
            )

        session.last_activity = time.time()

        return ResponseBuilder.build(
            status=Status.OK,
            session_token=session.token,
            server_nonce=session.nonce,
            trace_id=session.trace_id,
            details=b"Heartbeat acknowledged",
            advice="Session kept alive"
        )

    def _handle_terminate(self, req: ParsedRequest, session: Session) -> bytes:
        """Handle TERMINATE message."""
        old_state = session.state

        if session.state == SessionState.UNINITIALIZED:
            return ResponseBuilder.build(
                status=Status.ERROR,
                details=b"No session to terminate",
                advice="Nothing to close"
            )

        # Mark session as freed (for CVE-FAKE-006 check)
        session.freed = True
        session.state = SessionState.CLOSED

        # Remove from active sessions
        if session.token in self.sessions:
            del self.sessions[session.token]

        self.logger.state_transition(old_state, session.state, "TERMINATE")

        return ResponseBuilder.build(
            status=Status.OK,
            session_token=session.token,
            trace_id=session.trace_id,
            details=b"Session terminated",
            advice="Goodbye"
        )


# =============================================================================
# Server
# =============================================================================

class FeatureReferenceServer:
    """TCP server for feature_reference protocol."""

    def __init__(self, host: str = "0.0.0.0", port: int = 9999):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.logger = Logger(color_enabled=sys.stdout.isatty())
        self.handler = ProtocolHandler(self.logger)

    def start(self):
        """Start the server."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(5)
        self.running = True

        self.logger.banner()
        self.logger.info(f"Listening on {self.host}:{self.port}")
        self.logger.info("Intentional vulnerabilities active - find them all!")
        print()

        try:
            while self.running:
                try:
                    client_sock, addr = self.socket.accept()
                    self.logger.connection(addr, "connected")

                    thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_sock, addr),
                        daemon=True
                    )
                    thread.start()

                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.logger.error(f"Accept error: {e}")

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        finally:
            self.stop()

    def stop(self):
        """Stop the server."""
        self.running = False
        if self.socket:
            self.socket.close()

    def _handle_client(self, client_sock: socket.socket, addr: Tuple[str, int]):
        """
        Handle a client connection.

        Uses single-request mode: receives one request, sends response, closes.
        This matches the fuzzer's default 'per_test' connection mode for fast
        throughput (avoids waiting for read timeout).
        """
        try:
            # Receive data (single request)
            data = client_sock.recv(8192)
            if not data:
                return

            # Parse request
            req = ProtocolParser.parse(data)
            self.logger.request(req)

            if req.parse_error:
                self.logger.warning(f"Parse error: {req.parse_error}")
                response = ResponseBuilder.build(
                    status=Status.ERROR,
                    details=f"Parse error: {req.parse_error}".encode()[:256],
                    advice="Check message format"
                )
            else:
                # Handle request
                response = self.handler.handle(req, addr)

            # Decode response for logging
            if len(response) >= 6:
                status = response[5]
                # Extract details and advice lengths for logging
                token = struct.unpack('>Q', response[6:14])[0] if len(response) >= 14 else 0
                det_len = struct.unpack('>H', response[22:24])[0] if len(response) >= 24 else 0
                det_end = 24 + det_len
                details = response[24:det_end].decode('utf-8', errors='replace') if det_len > 0 else ""
                adv_len = response[det_end] if len(response) > det_end else 0
                advice = response[det_end+1:det_end+1+adv_len].decode('utf-8', errors='replace') if adv_len > 0 else ""

                self.logger.response(Status(status), token, details, advice)

            # Send response and close (single-request mode)
            client_sock.sendall(response)

        except ConnectionResetError:
            self.logger.connection(addr, "connection reset")
        except BrokenPipeError:
            self.logger.connection(addr, "broken pipe")
        except Exception as e:
            self.logger.error(f"Client handler error: {e}")
        finally:
            try:
                client_sock.close()
            except:
                pass
            self.logger.connection(addr, "disconnected")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Feature Reference Protocol Test Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
INTENTIONAL VULNERABILITIES:
  CVE-FAKE-001  Buffer overflow (payload > 2048)
  CVE-FAKE-002  Auth bypass (session_id = 0xDEADBEEF)
  CVE-FAKE-003  Integer overflow (payload_len >= 32768)
  CVE-FAKE-004  Null pointer (payload contains "CRASH")
  CVE-FAKE-005  Format string (payload contains %%s%%n)
  CVE-FAKE-006  Use-after-free (DATA_STREAM after TERMINATE)
  CVE-FAKE-007  Race condition (fragmented + urgent + more_frags)
  CVE-FAKE-008  Memory disclosure (encrypted without session)
  CVE-FAKE-009  State confusion (HEARTBEAT + ack + qos=7)
  CVE-FAKE-010  Heap corruption (all bits + seq=FFF + channel=F)

Find all 10 vulnerabilities using the fuzzer!
"""
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9999, help="Port to bind to")

    args = parser.parse_args()

    server = FeatureReferenceServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
