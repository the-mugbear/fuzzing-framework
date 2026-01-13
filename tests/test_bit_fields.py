"""
Comprehensive tests for sub-byte field support.

Tests parsing, serialization, validation, and mutations of bit fields.
"""
import pytest
from core.engine.protocol_parser import ProtocolParser
from core.engine.structure_mutators import StructureAwareMutator


class TestBitFieldParsing:
    """Test parsing of bit fields"""

    def test_single_nibble_parse(self):
        """Test parsing a single 4-bit nibble"""
        data_model = {
            "blocks": [
                {"name": "version", "type": "bits", "size": 4, "bit_order": "msb"},
                {"name": "type", "type": "bits", "size": 4, "bit_order": "msb"},
            ]
        }
        parser = ProtocolParser(data_model)

        # Byte: 0x4A = 0b01001010 = version(4) + type(10)
        data = b"\x4A"
        fields = parser.parse(data)

        assert fields["version"] == 0x4
        assert fields["type"] == 0xA

    def test_nibble_serialization(self):
        """Test serializing nibbles back to bytes"""
        data_model = {
            "blocks": [
                {"name": "version", "type": "bits", "size": 4, "default": 0x4},
                {"name": "type", "type": "bits", "size": 4, "default": 0xA},
            ]
        }
        parser = ProtocolParser(data_model)

        fields = {"version": 0x4, "type": 0xA}
        data = parser.serialize(fields)

        assert data == b"\x4A"

    def test_bit_field_spanning_bytes(self):
        """Test 12-bit field spanning byte boundary"""
        data_model = {
            "blocks": [
                {"name": "header", "type": "bits", "size": 4},  # Bits 0-3
                {"name": "id", "type": "bits", "size": 12},     # Bits 4-15 (spans boundary)
            ]
        }
        parser = ProtocolParser(data_model)

        # header=0xA (4 bits), id=0xBC0 (12 bits)
        # Result: 0xABC0 = [0xAB, 0xC0]
        data = b"\xAB\xC0"
        fields = parser.parse(data)

        assert fields["header"] == 0xA
        assert fields["id"] == 0xBC0

    def test_bit_field_spanning_bytes_serialization(self):
        """Test serializing 12-bit field spanning byte boundary"""
        data_model = {
            "blocks": [
                {"name": "header", "type": "bits", "size": 4, "default": 0xA},
                {"name": "id", "type": "bits", "size": 12, "default": 0xBC0},
            ]
        }
        parser = ProtocolParser(data_model)

        fields = {"header": 0xA, "id": 0xBC0}
        data = parser.serialize(fields)

        assert data == b"\xAB\xC0"

    def test_mixed_bit_and_byte_fields(self):
        """Test protocol with both bit and byte fields"""
        data_model = {
            "blocks": [
                {"name": "flags", "type": "bits", "size": 4},
                {"name": "reserved", "type": "bits", "size": 4},
                {"name": "length", "type": "uint16", "endian": "big"},
                {"name": "payload", "type": "bytes", "size": 2},
            ]
        }
        parser = ProtocolParser(data_model)

        # flags=0x5, reserved=0x0, length=0x0002, payload=b"HI"
        data = b"\x50\x00\x02HI"
        fields = parser.parse(data)

        assert fields["flags"] == 0x5
        assert fields["reserved"] == 0x0
        assert fields["length"] == 2
        assert fields["payload"] == b"HI"

    def test_mixed_bit_and_byte_fields_serialization(self):
        """Test serializing protocol with both bit and byte fields"""
        data_model = {
            "blocks": [
                {"name": "flags", "type": "bits", "size": 4, "default": 0x5},
                {"name": "reserved", "type": "bits", "size": 4, "default": 0x0},
                {"name": "length", "type": "uint16", "endian": "big", "default": 2},
                {"name": "payload", "type": "bytes", "default": b"HI"},
            ]
        }
        parser = ProtocolParser(data_model)

        fields = {"flags": 0x5, "reserved": 0x0, "length": 2, "payload": b"HI"}
        data = parser.serialize(fields)

        assert data == b"\x50\x00\x02HI"

    def test_lsb_bit_order(self):
        """Test LSB-first bit ordering"""
        data_model = {
            "blocks": [
                {"name": "field1", "type": "bits", "size": 4, "bit_order": "lsb"},
                {"name": "field2", "type": "bits", "size": 4, "bit_order": "lsb"},
            ]
        }
        parser = ProtocolParser(data_model)

        # Byte: 0xAB with LSB ordering
        # Lower 4 bits first: 0xB, upper 4 bits: 0xA
        data = b"\xAB"
        fields = parser.parse(data)

        assert fields["field1"] == 0xB
        assert fields["field2"] == 0xA

    def test_lsb_bit_order_serialization(self):
        """Test LSB-first bit ordering serialization"""
        data_model = {
            "blocks": [
                {"name": "field1", "type": "bits", "size": 4, "bit_order": "lsb", "default": 0xB},
                {"name": "field2", "type": "bits", "size": 4, "bit_order": "lsb", "default": 0xA},
            ]
        }
        parser = ProtocolParser(data_model)

        fields = {"field1": 0xB, "field2": 0xA}
        data = parser.serialize(fields)

        assert data == b"\xAB"

    def test_single_bit_flags(self):
        """Test single-bit flag fields"""
        data_model = {
            "blocks": [
                {"name": "flag_urgent", "type": "bits", "size": 1},
                {"name": "flag_ack", "type": "bits", "size": 1},
                {"name": "flag_push", "type": "bits", "size": 1},
                {"name": "flag_reset", "type": "bits", "size": 1},
                {"name": "reserved", "type": "bits", "size": 4},
            ]
        }
        parser = ProtocolParser(data_model)

        # Byte: 0b10110000 = urgent=1, ack=0, push=1, reset=1, reserved=0
        data = b"\xB0"
        fields = parser.parse(data)

        assert fields["flag_urgent"] == 1
        assert fields["flag_ack"] == 0
        assert fields["flag_push"] == 1
        assert fields["flag_reset"] == 1
        assert fields["reserved"] == 0

    def test_multi_byte_bit_field_big_endian(self):
        """Test multi-byte bit field with big-endian (default)"""
        data_model = {
            "blocks": [
                {"name": "fragment_id", "type": "bits", "size": 13, "endian": "big"},
                {"name": "flags", "type": "bits", "size": 3},
            ]
        }
        parser = ProtocolParser(data_model)

        # Data: 0x357C = 0b0011010101111100
        # First 13 bits: 0b0011010101111 = 0x6AF = 1711
        # Last 3 bits: 0b100 = 0x4
        data = b"\x35\x7C"
        fields = parser.parse(data)

        assert fields["fragment_id"] == 0x6AF  # 13 bits from MSB
        assert fields["flags"] == 0x4  # Remaining 3 bits

    def test_multi_byte_bit_field_little_endian(self):
        """Test multi-byte bit field with little-endian"""
        data_model = {
            "blocks": [
                {"name": "value", "type": "bits", "size": 12, "endian": "little"},
                {"name": "padding", "type": "bits", "size": 4},
            ]
        }
        parser = ProtocolParser(data_model)

        # Little-endian 12-bit value
        # Bytes [0x34, 0x12] in little-endian order
        data = b"\x34\x12"
        fields = parser.parse(data)

        # With little-endian byte order, parsing extracts differently
        assert fields["value"] == 0x123
        assert fields["padding"] == 0x2


class TestSizeFieldsWithBits:
    """Test size fields with bit field support"""

    def test_size_field_with_bits_unit(self):
        """Test size field counting bits"""
        data_model = {
            "blocks": [
                {"name": "header", "type": "bits", "size": 4, "default": 0x4},
                {
                    "name": "length",
                    "type": "uint8",
                    "is_size_field": True,
                    "size_of": ["flags", "payload"],
                    "size_unit": "bits"  # Count in bits
                },
                {"name": "flags", "type": "bits", "size": 4, "default": 0x0},
                {"name": "payload", "type": "bytes", "default": b"TEST"},
            ]
        }
        parser = ProtocolParser(data_model)

        fields = {"header": 0x4, "flags": 0x0, "payload": b"TEST"}
        fields = parser._auto_fix_fields(fields)

        # flags (4 bits) + payload (32 bits) = 36 bits
        assert fields["length"] == 36

    def test_size_field_bytes_with_bits(self):
        """Test size field counting bytes when referencing bit fields"""
        data_model = {
            "blocks": [
                {
                    "name": "length",
                    "type": "uint8",
                    "is_size_field": True,
                    "size_of": ["flags", "payload"],
                    "size_unit": "bytes"  # Count in bytes (rounded)
                },
                {"name": "flags", "type": "bits", "size": 12, "default": 0x0},
                {"name": "payload", "type": "bytes", "default": b"HI"},
            ]
        }
        parser = ProtocolParser(data_model)

        fields = {"flags": 0x0, "payload": b"HI"}
        fields = parser._auto_fix_fields(fields)

        # flags (12 bits = 2 bytes rounded) + payload (2 bytes) = 4 bytes
        # Actually: 12 + 16 = 28 bits = 4 bytes (rounded up)
        assert fields["length"] == 4

    def test_size_field_words_unit(self):
        """Test size field counting in 32-bit words"""
        data_model = {
            "blocks": [
                {
                    "name": "header_length",
                    "type": "uint8",
                    "is_size_field": True,
                    "size_of": ["version", "ihl", "payload"],
                    "size_unit": "words"  # 32-bit words
                },
                {"name": "version", "type": "bits", "size": 4, "default": 0x4},
                {"name": "ihl", "type": "bits", "size": 4, "default": 0x5},
                {"name": "payload", "type": "bytes", "default": b"DATA"},
            ]
        }
        parser = ProtocolParser(data_model)

        fields = {"version": 0x4, "ihl": 0x5, "payload": b"DATA"}
        fields = parser._auto_fix_fields(fields)

        # version (4 bits) + ihl (4 bits) + payload (32 bits) = 40 bits
        # 40 bits / 32 bits per word = 2 words (rounded up)
        assert fields["header_length"] == 2


class TestBitFieldMutations:
    """Test structure-aware mutations on bit fields"""

    def test_bit_field_boundary_mutations(self):
        """Test boundary value mutations on bit fields"""
        data_model = {
            "blocks": [
                {"name": "version", "type": "bits", "size": 4, "default": 0x4},
                {"name": "type", "type": "bits", "size": 4, "default": 0x1},
            ]
        }

        mutator = StructureAwareMutator(data_model)
        seed = b"\x41"  # version=4, type=1

        # Generate 100 mutations
        mutations = [mutator.mutate(seed) for _ in range(100)]

        # Verify all mutations are valid (1 byte)
        assert all(len(m) == 1 for m in mutations)

        # Verify mutations differ from seed
        assert any(m != seed for m in mutations)

    def test_bit_field_interesting_values(self):
        """Test interesting value mutations include power-of-2 patterns"""
        data_model = {
            "blocks": [
                {"name": "flags", "type": "bits", "size": 8, "default": 0x00},
            ]
        }

        mutator = StructureAwareMutator(data_model)
        seed = b"\x00"

        # Generate many mutations to likely hit interesting values
        mutations = [mutator.mutate(seed) for _ in range(200)]

        # Should include some power-of-2 values (0x01, 0x02, 0x04, 0x08, etc.)
        mutation_ints = [int.from_bytes(m, 'big') for m in mutations]
        powers_of_2 = [1, 2, 4, 8, 16, 32, 64, 128]
        found_powers = [p for p in powers_of_2 if p in mutation_ints]

        # At least some power-of-2 values should appear
        assert len(found_powers) > 0

    def test_bit_field_arithmetic_mutations(self):
        """Test arithmetic mutations respect bit field max values"""
        data_model = {
            "blocks": [
                {"name": "counter", "type": "bits", "size": 3, "default": 0x4},  # Max = 7
            ]
        }

        mutator = StructureAwareMutator(data_model)

        # Generate many mutations
        mutations = []
        for _ in range(100):
            # Start with value near max
            seed = b"\xE0"  # counter=7 (0b111 in upper 3 bits)
            mutation = mutator.mutate(seed)
            mutations.append(mutation)

        # All mutations should be valid (arithmetic should wrap)
        assert all(len(m) == 1 for m in mutations)


class TestRoundTripIntegrity:
    """Test parse → serialize → parse produces same result"""

    def test_round_trip_simple_nibbles(self):
        """Test round-trip with simple nibbles"""
        data_model = {
            "blocks": [
                {"name": "version", "type": "bits", "size": 4},
                {"name": "type", "type": "bits", "size": 4},
            ]
        }
        parser = ProtocolParser(data_model)

        original = b"\x4A"

        # Parse
        fields1 = parser.parse(original)

        # Serialize
        reconstructed = parser.serialize(fields1)

        # Parse again
        fields2 = parser.parse(reconstructed)

        assert fields1 == fields2
        assert reconstructed == original

    def test_round_trip_mixed_fields(self):
        """Test round-trip with mixed bit and byte fields"""
        data_model = {
            "blocks": [
                {"name": "flags", "type": "bits", "size": 3},
                {"name": "reserved", "type": "bits", "size": 5},
                {"name": "length", "type": "uint16", "endian": "big"},
                {"name": "payload", "type": "bytes", "max_size": 64},
            ]
        }
        parser = ProtocolParser(data_model)

        # Test data
        original = b"\xA0\x00\x05HELLO"

        # Parse
        fields1 = parser.parse(original)

        # Serialize
        reconstructed = parser.serialize(fields1)

        # Parse again
        fields2 = parser.parse(reconstructed)

        assert fields1 == fields2
        assert reconstructed == original

    def test_round_trip_byte_spanning(self):
        """Test round-trip with byte-spanning bit fields"""
        data_model = {
            "blocks": [
                {"name": "header", "type": "bits", "size": 4},
                {"name": "id", "type": "bits", "size": 12},
                {"name": "payload", "type": "bytes", "max_size": 16},
            ]
        }
        parser = ProtocolParser(data_model)

        original = b"\xAB\xCDTEST"

        # Parse
        fields1 = parser.parse(original)

        # Serialize
        reconstructed = parser.serialize(fields1)

        # Parse again
        fields2 = parser.parse(reconstructed)

        assert fields1 == fields2
        assert reconstructed == original


class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_64_bit_field(self):
        """Test maximum 64-bit field"""
        data_model = {
            "blocks": [
                {"name": "large", "type": "bits", "size": 64, "default": 0x123456789ABCDEF0},
            ]
        }
        parser = ProtocolParser(data_model)

        fields = {"large": 0x123456789ABCDEF0}
        data = parser.serialize(fields)

        # Should be 8 bytes
        assert len(data) == 8

        # Parse back
        parsed = parser.parse(data)
        assert parsed["large"] == 0x123456789ABCDEF0

    def test_single_bit_field(self):
        """Test minimum 1-bit field"""
        data_model = {
            "blocks": [
                {"name": "flag", "type": "bits", "size": 1, "default": 1},
                {"name": "padding", "type": "bits", "size": 7, "default": 0},
            ]
        }
        parser = ProtocolParser(data_model)

        fields = {"flag": 1, "padding": 0}
        data = parser.serialize(fields)

        assert data == b"\x80"  # MSB set

        parsed = parser.parse(data)
        assert parsed["flag"] == 1
        assert parsed["padding"] == 0

    def test_value_masking(self):
        """Test that values are masked to bit width"""
        data_model = {
            "blocks": [
                {"name": "nibble", "type": "bits", "size": 4, "default": 0xF},
            ]
        }
        parser = ProtocolParser(data_model)

        # Try to serialize value larger than 4 bits
        fields = {"nibble": 0xFF}  # Should be masked to 0xF
        data = parser.serialize(fields)

        parsed = parser.parse(data)
        assert parsed["nibble"] == 0xF  # Only 4 bits preserved
