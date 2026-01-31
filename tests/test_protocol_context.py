"""
Tests for ProtocolContext and related orchestrated session functionality.

Tests cover:
- ProtocolContext basic operations (get, set, clear)
- Snapshot and restore functionality
- Bytes serialization round-trip
- ProtocolParser serialize with context
- ProtocolParser dynamic value generation
"""
import pytest
from datetime import datetime

from core.engine.protocol_context import (
    ProtocolContext,
    ContextError,
    ContextKeyNotFoundError,
)
from core.engine.protocol_parser import ProtocolParser, SerializationError


class TestProtocolContext:
    """Tests for ProtocolContext class."""

    def test_get_set_basic(self):
        """Test basic get/set operations."""
        ctx = ProtocolContext()
        ctx.set("token", 0xABCD)
        assert ctx.get("token") == 0xABCD

    def test_get_default(self):
        """Test get returns default for missing key."""
        ctx = ProtocolContext()
        assert ctx.get("missing") is None
        assert ctx.get("missing", "default") == "default"

    def test_has_key(self):
        """Test has() method."""
        ctx = ProtocolContext()
        assert not ctx.has("key")
        ctx.set("key", "value")
        assert ctx.has("key")

    def test_delete_key(self):
        """Test delete() method."""
        ctx = ProtocolContext()
        ctx.set("key", "value")
        assert ctx.delete("key") is True
        assert not ctx.has("key")
        assert ctx.delete("missing") is False

    def test_keys(self):
        """Test keys() method."""
        ctx = ProtocolContext()
        ctx.set("a", 1)
        ctx.set("b", 2)
        ctx.set("c", 3)
        assert sorted(ctx.keys()) == ["a", "b", "c"]

    def test_clear(self):
        """Test clear() method."""
        ctx = ProtocolContext()
        ctx.set("token", 0xABCD)
        ctx.bootstrap_complete = True

        ctx.clear()

        assert ctx.get("token") is None
        assert ctx.bootstrap_complete is False

    def test_last_updated(self):
        """Test last_updated tracking."""
        ctx = ProtocolContext()
        assert ctx.last_updated is None

        ctx.set("key", "value")
        assert ctx.last_updated is not None
        assert isinstance(ctx.last_updated, datetime)


class TestProtocolContextSnapshot:
    """Tests for snapshot/restore functionality."""

    def test_snapshot_restore_basic(self):
        """Test basic snapshot and restore."""
        ctx = ProtocolContext()
        ctx.set("token", 0xABCD)
        ctx.set("nonce", 12345)
        ctx.bootstrap_complete = True

        snapshot = ctx.snapshot()

        ctx2 = ProtocolContext()
        ctx2.restore(snapshot)

        assert ctx2.get("token") == 0xABCD
        assert ctx2.get("nonce") == 12345
        assert ctx2.bootstrap_complete is True

    def test_snapshot_restore_bytes(self):
        """Test bytes values are properly serialized/deserialized."""
        ctx = ProtocolContext()
        ctx.set("data", b"\x01\x02\x03\x04")

        snapshot = ctx.snapshot()

        # Verify bytes are hex-encoded in snapshot
        assert snapshot["values"]["data"]["_type"] == "bytes"
        assert snapshot["values"]["data"]["value"] == "01020304"

        ctx2 = ProtocolContext()
        ctx2.restore(snapshot)

        assert ctx2.get("data") == b"\x01\x02\x03\x04"

    def test_snapshot_restore_datetime(self):
        """Test datetime values are properly serialized/deserialized."""
        ctx = ProtocolContext()
        now = datetime.utcnow()
        ctx.set("timestamp", now)

        snapshot = ctx.snapshot()

        ctx2 = ProtocolContext()
        ctx2.restore(snapshot)

        restored = ctx2.get("timestamp")
        assert isinstance(restored, datetime)
        # Allow for microsecond differences in serialization
        assert abs((restored - now).total_seconds()) < 1

    def test_snapshot_include_keys(self):
        """Test snapshot with include_keys filter."""
        ctx = ProtocolContext()
        ctx.set("include_me", 1)
        ctx.set("exclude_me", 2)

        snapshot = ctx.snapshot(include_keys=["include_me"])

        assert "include_me" in snapshot["values"]
        assert "exclude_me" not in snapshot["values"]

    def test_snapshot_exclude_keys(self):
        """Test snapshot with exclude_keys filter."""
        ctx = ProtocolContext()
        ctx.set("keep", 1)
        ctx.set("sensitive", "secret")

        snapshot = ctx.snapshot(exclude_keys=["sensitive"])

        assert "keep" in snapshot["values"]
        assert "sensitive" not in snapshot["values"]

    def test_copy(self):
        """Test deep copy functionality."""
        ctx = ProtocolContext()
        ctx.set("token", 0xABCD)
        ctx.set("data", {"nested": [1, 2, 3]})
        ctx.bootstrap_complete = True

        ctx2 = ctx.copy()

        # Modify original
        ctx.set("token", 0xDEAD)
        ctx.get("data")["nested"].append(4)

        # Copy should be unchanged
        assert ctx2.get("token") == 0xABCD
        assert ctx2.get("data")["nested"] == [1, 2, 3]


class TestProtocolParserWithContext:
    """Tests for ProtocolParser serialize with context."""

    def test_serialize_with_from_context(self):
        """Test serialization with from_context field injection."""
        data_model = {
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4, "default": b"TEST"},
                {"name": "token", "type": "uint32", "from_context": "auth_token", "endian": "big"},
            ]
        }
        parser = ProtocolParser(data_model)

        ctx = ProtocolContext()
        ctx.set("auth_token", 0x12345678)

        result = parser.serialize({}, context=ctx)

        assert result == b"TEST\x12\x34\x56\x78"

    def test_serialize_missing_context_raises(self):
        """Test that missing context raises SerializationError."""
        data_model = {
            "blocks": [
                {"name": "token", "type": "uint32", "from_context": "auth_token"},
            ]
        }
        parser = ProtocolParser(data_model)

        with pytest.raises(SerializationError, match="requires context"):
            parser.serialize({}, context=None)

    def test_serialize_missing_context_key_raises(self):
        """Test that missing context key raises SerializationError."""
        data_model = {
            "blocks": [
                {"name": "token", "type": "uint32", "from_context": "missing_key"},
            ]
        }
        parser = ProtocolParser(data_model)

        ctx = ProtocolContext()
        ctx.set("other_key", 123)

        with pytest.raises(SerializationError, match="not found"):
            parser.serialize({}, context=ctx)

    def test_serialize_explicit_overrides_context(self):
        """Test that explicit field value overrides from_context."""
        data_model = {
            "blocks": [
                {"name": "token", "type": "uint32", "from_context": "auth_token", "endian": "big"},
            ]
        }
        parser = ProtocolParser(data_model)

        ctx = ProtocolContext()
        ctx.set("auth_token", 0xAAAAAAAA)

        # Explicit value should win
        result = parser.serialize({"token": 0xBBBBBBBB}, context=ctx)

        assert result == b"\xBB\xBB\xBB\xBB"

    def test_serialize_with_transform(self):
        """Test serialization with transform applied to context value."""
        data_model = {
            "blocks": [
                {
                    "name": "masked_token",
                    "type": "uint8",
                    "from_context": "token",
                    "transform": [
                        {"operation": "and_mask", "value": 0x0F},
                    ],
                },
            ]
        }
        parser = ProtocolParser(data_model)

        ctx = ProtocolContext()
        ctx.set("token", 0xAB)  # Should become 0x0B after mask

        result = parser.serialize({}, context=ctx)

        assert result == b"\x0B"

    def test_serialize_with_multiple_transforms(self):
        """Test serialization with multiple transforms in pipeline."""
        data_model = {
            "blocks": [
                {
                    "name": "result",
                    "type": "uint8",
                    "from_context": "value",
                    "transform": [
                        {"operation": "and_mask", "value": 0x0F},
                        {"operation": "shift_left", "value": 4},
                    ],
                },
            ]
        }
        parser = ProtocolParser(data_model)

        ctx = ProtocolContext()
        ctx.set("value", 0xAB)  # 0xAB & 0x0F = 0x0B, << 4 = 0xB0

        result = parser.serialize({}, context=ctx)

        assert result == b"\xB0"


class TestProtocolParserDynamicGeneration:
    """Tests for dynamic value generation in ProtocolParser."""

    def test_generate_unix_timestamp(self):
        """Test unix_timestamp generator."""
        data_model = {
            "blocks": [
                {"name": "ts", "type": "uint32", "generate": "unix_timestamp", "endian": "big"},
            ]
        }
        parser = ProtocolParser(data_model)

        before = int(datetime.utcnow().timestamp())
        result = parser.serialize({})
        after = int(datetime.utcnow().timestamp())

        # Parse the timestamp back
        import struct
        ts = struct.unpack(">I", result)[0]

        assert before <= ts <= after

    def test_generate_sequence(self):
        """Test sequence generator increments."""
        data_model = {
            "blocks": [
                {"name": "seq", "type": "uint8", "generate": "sequence"},
            ]
        }
        parser = ProtocolParser(data_model)

        r1 = parser.serialize({})
        r2 = parser.serialize({})
        r3 = parser.serialize({})

        assert r1 == b"\x01"
        assert r2 == b"\x02"
        assert r3 == b"\x03"

    def test_generate_random_bytes(self):
        """Test random_bytes generator."""
        data_model = {
            "blocks": [
                {"name": "nonce", "type": "bytes", "size": 16, "generate": "random_bytes:16"},
            ]
        }
        parser = ProtocolParser(data_model)

        r1 = parser.serialize({})
        r2 = parser.serialize({})

        assert len(r1) == 16
        assert len(r2) == 16
        # Random bytes should differ (with very high probability)
        assert r1 != r2

    def test_explicit_overrides_generate(self):
        """Test that explicit value overrides generate."""
        data_model = {
            "blocks": [
                {"name": "seq", "type": "uint8", "generate": "sequence"},
            ]
        }
        parser = ProtocolParser(data_model)

        result = parser.serialize({"seq": 0xFF})

        assert result == b"\xFF"


class TestContextKeyNotFoundError:
    """Tests for ContextKeyNotFoundError."""

    def test_error_message_basic(self):
        """Test basic error message."""
        err = ContextKeyNotFoundError("missing_key")
        assert "missing_key" in str(err)
        assert "not found" in str(err)

    def test_error_message_with_available_keys(self):
        """Test error message includes available keys."""
        err = ContextKeyNotFoundError("missing", available_keys=["a", "b", "c"])
        assert "missing" in str(err)
        assert "a" in str(err)
        assert "b" in str(err)
        assert "c" in str(err)
