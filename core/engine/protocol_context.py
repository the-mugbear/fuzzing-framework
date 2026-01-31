"""
Protocol Context - Key-value store for orchestrated session data.

Provides a runtime store for values that flow between protocol stages:
- Bootstrap stages export values (tokens, nonces, intervals) to context
- Fuzz target stages consume values via from_context field attributes
- Context is persisted with sessions for resume capability
- Context snapshots are stored with executions for replay
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class ProtocolContext:
    """
    Runtime key-value store for session-scoped values in orchestrated sessions.

    Used to pass data between protocol stages:
    - Bootstrap stages export response values into context
    - Fuzz target stages inject context values into outgoing messages

    Example:
        ctx = ProtocolContext()
        ctx.set("auth_token", 0x12345678)
        ctx.set("nonce", b"\\x00\\x01\\x02\\x03")

        # Later during serialization
        token = ctx.get("auth_token")  # Returns 0x12345678
    """

    values: Dict[str, Any] = field(default_factory=dict)
    bootstrap_complete: bool = False
    last_updated: Optional[datetime] = None

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a context value.

        Args:
            key: Context key to retrieve
            default: Value to return if key not found

        Returns:
            The stored value or default
        """
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set a context value.

        Args:
            key: Context key to store
            value: Value to store (must be JSON-serializable or bytes)
        """
        self.values[key] = value
        self.last_updated = datetime.utcnow()
        logger.debug("context_value_set", key=key, value_type=type(value).__name__)

    def has(self, key: str) -> bool:
        """Check if a context key exists."""
        return key in self.values

    def delete(self, key: str) -> bool:
        """
        Delete a context key.

        Returns:
            True if key was deleted, False if it didn't exist
        """
        if key in self.values:
            del self.values[key]
            self.last_updated = datetime.utcnow()
            return True
        return False

    def keys(self) -> List[str]:
        """Return all context keys."""
        return list(self.values.keys())

    def clear(self) -> None:
        """
        Clear all context values.

        Used when re-bootstrapping after connection drop.
        """
        self.values.clear()
        self.bootstrap_complete = False
        self.last_updated = None
        logger.debug("context_cleared")

    def snapshot(
        self,
        include_keys: Optional[List[str]] = None,
        exclude_keys: Optional[List[str]] = None,
        max_size_bytes: int = 65536,
    ) -> Dict[str, Any]:
        """
        Create serializable snapshot for persistence and replay.

        Args:
            include_keys: If provided, only snapshot these keys
            exclude_keys: Keys to exclude from snapshot
            max_size_bytes: Maximum snapshot size (truncate if exceeded)

        Returns:
            JSON-serializable dictionary
        """
        # Filter values based on include/exclude
        values_to_snapshot = {}
        for key, value in self.values.items():
            if include_keys and key not in include_keys:
                continue
            if exclude_keys and key in exclude_keys:
                continue
            values_to_snapshot[key] = value

        # Serialize values
        serialized = self._serialize_values(values_to_snapshot)

        snapshot = {
            "values": serialized,
            "bootstrap_complete": self.bootstrap_complete,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }

        # Check size (rough estimate)
        try:
            snapshot_json = json.dumps(snapshot)
            if len(snapshot_json) > max_size_bytes:
                logger.warning(
                    "context_snapshot_truncated",
                    actual_size=len(snapshot_json),
                    max_size=max_size_bytes,
                )
                # Mark as truncated for UI warning
                snapshot["truncated"] = True
                snapshot["original_key_count"] = len(serialized)
        except (TypeError, ValueError) as e:
            logger.warning("context_snapshot_serialization_warning", error=str(e))

        return snapshot

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """
        Restore context from a snapshot.

        Args:
            snapshot: Previously created snapshot dictionary
        """
        self.values = self._deserialize_values(snapshot.get("values", {}))
        self.bootstrap_complete = snapshot.get("bootstrap_complete", False)
        ts = snapshot.get("last_updated")
        self.last_updated = datetime.fromisoformat(ts) if ts else None
        logger.debug(
            "context_restored",
            key_count=len(self.values),
            bootstrap_complete=self.bootstrap_complete,
        )

    def _serialize_values(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert values to JSON-serializable format.

        Bytes are hex-encoded with a type marker for round-trip fidelity.
        """
        result = {}
        for key, value in values.items():
            if isinstance(value, bytes):
                result[key] = {"_type": "bytes", "value": value.hex()}
            elif isinstance(value, bytearray):
                result[key] = {"_type": "bytes", "value": bytes(value).hex()}
            elif isinstance(value, datetime):
                result[key] = {"_type": "datetime", "value": value.isoformat()}
            else:
                # Assume JSON-serializable (int, str, float, list, dict, bool, None)
                result[key] = value
        return result

    def _deserialize_values(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Restore values from JSON format.

        Reverses the type markers applied during serialization.
        """
        result = {}
        for key, value in values.items():
            if isinstance(value, dict):
                value_type = value.get("_type")
                if value_type == "bytes":
                    result[key] = bytes.fromhex(value["value"])
                elif value_type == "datetime":
                    result[key] = datetime.fromisoformat(value["value"])
                else:
                    result[key] = value
            else:
                result[key] = value
        return result

    def merge(self, other: "ProtocolContext") -> None:
        """
        Merge values from another context into this one.

        Values from 'other' overwrite values in 'self' for duplicate keys.
        """
        for key, value in other.values.items():
            self.values[key] = value
        if other.bootstrap_complete:
            self.bootstrap_complete = True
        self.last_updated = datetime.utcnow()

    def copy(self) -> "ProtocolContext":
        """Create a deep copy of this context."""
        new_ctx = ProtocolContext()
        new_ctx.values = copy.deepcopy(self.values)
        new_ctx.bootstrap_complete = self.bootstrap_complete
        new_ctx.last_updated = self.last_updated
        return new_ctx


class ContextError(Exception):
    """Raised when context operations fail."""
    pass


class ContextKeyNotFoundError(ContextError):
    """Raised when a required context key is not found."""

    def __init__(self, key: str, available_keys: Optional[List[str]] = None):
        self.key = key
        self.available_keys = available_keys or []
        msg = f"Context key '{key}' not found"
        if self.available_keys:
            msg += f". Available keys: {', '.join(self.available_keys)}"
        super().__init__(msg)
