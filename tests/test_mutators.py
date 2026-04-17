"""Tests for the mutation engine and individual mutators."""
import pytest
from core.engine.mutators import (
    BitFlipMutator,
    ByteFlipMutator,
    ArithmeticMutator,
    InterestingValueMutator,
    HavocMutator,
    SpliceMutator,
    MutationEngine,
)


# ---------------------------------------------------------------------------
# Individual mutator tests
# ---------------------------------------------------------------------------

class TestBitFlipMutator:
    def test_flips_at_least_one_bit(self):
        data = b"\x00" * 64
        mutator = BitFlipMutator(flip_ratio=0.01)
        mutated = mutator.mutate(data)
        assert mutated != data
        assert len(mutated) == len(data)

    def test_empty_input_returns_empty(self):
        assert BitFlipMutator().mutate(b"") == b""

    def test_preserves_length(self):
        data = b"ABCDEFGHIJ"
        assert len(BitFlipMutator().mutate(data)) == len(data)


class TestByteFlipMutator:
    def test_flips_bytes(self):
        data = b"\x00" * 64
        mutated = ByteFlipMutator(flip_ratio=0.1).mutate(data)
        assert mutated != data
        assert len(mutated) == len(data)

    def test_empty_input(self):
        assert ByteFlipMutator().mutate(b"") == b""


class TestArithmeticMutator:
    def test_mutates_4byte_value(self):
        data = b"\x00\x00\x00\x00\x00\x00\x00\x00"
        mutated = ArithmeticMutator().mutate(data)
        assert mutated != data
        assert len(mutated) == len(data)

    def test_short_input_unchanged(self):
        data = b"\x01\x02"
        assert ArithmeticMutator().mutate(data) == data


class TestInterestingValueMutator:
    def test_injects_boundary_value(self):
        data = b"\x41" * 16
        mutated = InterestingValueMutator().mutate(data)
        assert mutated != data
        assert len(mutated) == len(data)

    def test_short_input_unchanged(self):
        assert InterestingValueMutator().mutate(b"\x00") == b"\x00"


class TestHavocMutator:
    def test_produces_different_output(self):
        data = b"A" * 64
        mutator = HavocMutator()
        # Havoc is random; give it multiple chances to produce a mutation
        any_different = any(mutator.mutate(data) != data for _ in range(10))
        assert any_different

    def test_empty_input(self):
        assert HavocMutator().mutate(b"") == b""

    def test_respects_max_size(self):
        data = b"B" * 100
        mutated = HavocMutator().mutate(data)
        # Havoc can grow but has a ceiling from settings.havoc_max_size
        assert len(mutated) < 50_000


class TestSpliceMutator:
    def test_splices_two_seeds(self):
        corpus = [b"AAAA", b"BBBB", b"CCCC"]
        mutator = SpliceMutator(corpus)
        mutated = mutator.mutate(b"AAAA")
        # Splice should produce something (may equal input by chance, run several)
        results = {mutator.mutate(b"AAAA") for _ in range(20)}
        assert len(results) > 1  # At least some variation

    def test_single_seed_unchanged(self):
        corpus = [b"AAAA"]
        assert SpliceMutator(corpus).mutate(b"AAAA") == b"AAAA"


# ---------------------------------------------------------------------------
# MutationEngine tests
# ---------------------------------------------------------------------------

class TestMutationEngine:
    @pytest.fixture
    def seeds(self):
        return [
            b"STCP\x00\x00\x00\x05\x01HELLO",
            b"STCP\x00\x00\x00\x04\x02TEST",
        ]

    def test_byte_level_mode(self, seeds):
        engine = MutationEngine(seeds, mutation_mode="byte_level")
        mutated = engine.generate_test_case(seeds[0])
        assert mutated != seeds[0]
        meta = engine.get_last_metadata()
        assert meta["strategy"] == "byte_level"
        assert len(meta["mutators"]) > 0

    def test_structure_aware_mode_with_data_model(self, seeds):
        data_model = {
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4, "default": b"STCP", "mutable": False},
                {"name": "length", "type": "uint32", "endian": "big", "is_size_field": True, "size_of": "payload"},
                {"name": "command", "type": "uint8"},
                {"name": "payload", "type": "bytes", "max_size": 1024, "default": b""},
            ]
        }
        engine = MutationEngine(seeds, data_model=data_model, mutation_mode="structure_aware")
        mutated = engine.generate_test_case(seeds[0])
        meta = engine.get_last_metadata()
        assert meta["strategy"] == "structure_aware"
        # Immutable magic header should be preserved
        assert mutated[:4] == b"STCP"

    def test_hybrid_mode_produces_both_strategies(self, seeds):
        data_model = {
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4, "default": b"STCP", "mutable": False},
                {"name": "length", "type": "uint32", "endian": "big", "is_size_field": True, "size_of": "payload"},
                {"name": "command", "type": "uint8"},
                {"name": "payload", "type": "bytes", "max_size": 1024, "default": b""},
            ]
        }
        engine = MutationEngine(seeds, data_model=data_model, mutation_mode="hybrid")
        strategies_seen = set()
        for _ in range(50):
            engine.generate_test_case(seeds[0])
            strategies_seen.add(engine.get_last_metadata()["strategy"])
        assert "byte_level" in strategies_seen
        assert "structure_aware" in strategies_seen

    def test_enabled_mutators_filtering(self, seeds):
        engine = MutationEngine(seeds, enabled_mutators=["bitflip"], mutation_mode="byte_level")
        engine.generate_test_case(seeds[0])
        meta = engine.get_last_metadata()
        assert meta["mutators"] == ["bitflip"]

    def test_invalid_mutator_names_fall_back(self, seeds):
        engine = MutationEngine(seeds, enabled_mutators=["nonexistent"])
        # Should fall back to all available mutators
        assert len(engine.enabled_mutators) == len(engine.mutators)

    def test_generate_batch(self, seeds):
        engine = MutationEngine(seeds, mutation_mode="byte_level")
        batch = engine.generate_batch(10)
        assert len(batch) == 10
        assert all(isinstance(tc, bytes) for tc in batch)

    def test_available_mutators_static(self):
        names = MutationEngine.available_mutators()
        assert "bitflip" in names
        assert "havoc" in names
        assert len(names) >= 6

    def test_available_mutation_modes_static(self):
        modes = MutationEngine.available_mutation_modes()
        mode_names = [m["name"] for m in modes]
        assert "byte_level" in mode_names
        assert "hybrid" in mode_names
        assert "structure_aware" in mode_names
