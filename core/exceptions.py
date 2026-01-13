"""
Custom Exception Hierarchy for Fuzzer

Provides structured exceptions for better error handling and recovery.
All custom exceptions inherit from FuzzerError base class.
"""
from typing import Optional


class FuzzerError(Exception):
    """
    Base exception for all fuzzer-specific errors.

    All custom exceptions should inherit from this class to allow
    catching all fuzzer errors with a single except clause.
    """
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# Configuration and Initialization Errors

class ConfigurationError(FuzzerError):
    """
    Invalid configuration or settings.

    Raised when configuration validation fails or required settings are missing.
    Examples: Invalid environment variables, malformed config files.
    """
    pass


class PluginError(FuzzerError):
    """
    Plugin loading or validation failures.

    Raised when protocol plugins fail to load, validate, or initialize.
    """
    pass


class PluginLoadError(PluginError):
    """Plugin file cannot be loaded or imported."""
    pass


class PluginValidationError(PluginError):
    """Plugin structure or data_model validation failed."""
    pass


# Protocol and Parsing Errors

class ProtocolError(FuzzerError):
    """
    Protocol-related errors during parsing or serialization.

    Base class for all protocol handling errors.
    """
    pass


class ParseError(ProtocolError):
    """Failed to parse message according to protocol definition."""
    pass


class SerializationError(ProtocolError):
    """Failed to serialize fields to binary format."""
    pass


class FieldValidationError(ProtocolError):
    """Field value doesn't match protocol constraints."""
    pass


# Network and Transport Errors

class TransportError(FuzzerError):
    """
    Network transport failures.

    Base class for all network communication errors.
    Distinguishes network issues from target crashes.
    """
    pass


class ConnectionError(TransportError):
    """Failed to establish connection to target."""
    pass


class ConnectionRefusedError(ConnectionError):
    """Target actively refused connection (ECONNREFUSED)."""
    pass


class ConnectionTimeoutError(TransportError):
    """Connection attempt timed out."""
    pass


class SendError(TransportError):
    """Failed to send data to target."""
    pass


class ReceiveError(TransportError):
    """Failed to receive response from target."""
    pass


class ReceiveTimeoutError(ReceiveError):
    """Timeout waiting for response (potential hang)."""
    pass


# Session Management Errors

class SessionError(FuzzerError):
    """
    Fuzzing session lifecycle errors.

    Base class for session management issues.
    """
    pass


class SessionNotFoundError(SessionError):
    """Requested session does not exist."""
    pass


class SessionStateError(SessionError):
    """Invalid operation for current session state."""
    def __init__(self, message: str, current_state: str, expected_state: Optional[str] = None):
        super().__init__(message, {"current_state": current_state, "expected_state": expected_state})
        self.current_state = current_state
        self.expected_state = expected_state


class SessionInitializationError(SessionError):
    """Failed to initialize session (no seeds, invalid protocol, etc)."""
    pass


# Corpus and Storage Errors

class CorpusError(FuzzerError):
    """
    Corpus store and seed management errors.

    Base class for corpus-related issues.
    """
    pass


class SeedNotFoundError(CorpusError):
    """Requested seed does not exist in corpus."""
    pass


class CorpusStorageError(CorpusError):
    """Failed to read/write corpus data."""
    pass


class FindingSaveError(CorpusError):
    """Failed to save crash finding to disk."""
    pass


# Mutation Engine Errors

class MutationError(FuzzerError):
    """
    Mutation engine failures.

    Base class for mutation-related errors.
    """
    pass


class MutatorNotFoundError(MutationError):
    """Requested mutator doesn't exist."""
    pass


class MutationFailedError(MutationError):
    """Mutation operation failed unexpectedly."""
    pass


# Stateful Fuzzing Errors

class StatefulFuzzingError(FuzzerError):
    """
    State machine fuzzing errors.

    Base class for stateful fuzzing issues.
    """
    pass


class StateTransitionError(StatefulFuzzingError):
    """Invalid state transition attempted."""
    pass


class StateNotFoundError(StatefulFuzzingError):
    """Referenced state doesn't exist in state model."""
    pass


# Resource Management Errors

class ResourceError(FuzzerError):
    """
    Resource exhaustion or limits exceeded.

    Base class for resource-related errors.
    """
    pass


class MemoryLimitError(ResourceError):
    """Memory usage exceeded configured limits."""
    pass


class RateLimitError(ResourceError):
    """Rate limit exceeded."""
    pass


class QueueFullError(ResourceError):
    """Queue capacity exceeded."""
    pass


# Agent Communication Errors

class AgentError(FuzzerError):
    """
    Agent communication and coordination errors.

    Base class for agent-related issues.
    """
    pass


class AgentNotFoundError(AgentError):
    """Agent is not registered or has disconnected."""
    pass


class AgentCommunicationError(AgentError):
    """Failed to communicate with agent."""
    pass


class AgentTimeoutError(AgentError):
    """Agent didn't respond within timeout."""
    pass


# Validation and Assertion Errors

class ValidationError(FuzzerError):
    """
    Data validation failures.

    Raised when input data doesn't meet validation requirements.
    """
    pass


class InvariantViolation(FuzzerError):
    """
    Internal invariant violated.

    Indicates a bug in the fuzzer itself (should never happen).
    """
    pass
