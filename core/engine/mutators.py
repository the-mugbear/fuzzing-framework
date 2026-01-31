"""
Mutation strategies for test case generation

Implements various mutation strategies from the blueprint:
- Bit flipping
- Byte flipping
- Arithmetic mutations
- Interesting values (boundary values)
- Havoc (random heavy mutations)
- Structure-aware mutations (NEW - respects protocol grammar)
"""
import random
import struct
from typing import Any, Dict, List, Optional

import structlog

from core.config import settings

logger = structlog.get_logger()


class Mutator:
    """Base mutator class"""

    def mutate(self, data: bytes) -> bytes:
        """Apply mutation to data"""
        raise NotImplementedError


class BitFlipMutator(Mutator):
    """Flip random bits in the input"""

    def __init__(self, flip_ratio: float = 0.01):
        self.flip_ratio = flip_ratio

    def mutate(self, data: bytes) -> bytes:
        if not data:
            return data

        data_array = bytearray(data)
        num_bits = len(data) * 8
        num_flips = max(1, int(num_bits * self.flip_ratio))

        for _ in range(num_flips):
            bit_pos = random.randint(0, num_bits - 1)
            byte_pos = bit_pos // 8
            bit_offset = bit_pos % 8
            data_array[byte_pos] ^= 1 << bit_offset

        return bytes(data_array)


class ByteFlipMutator(Mutator):
    """Replace random bytes with random values"""

    def __init__(self, flip_ratio: float = 0.05):
        self.flip_ratio = flip_ratio

    def mutate(self, data: bytes) -> bytes:
        if not data:
            return data

        data_array = bytearray(data)
        num_flips = max(1, int(len(data) * self.flip_ratio))

        for _ in range(num_flips):
            pos = random.randint(0, len(data_array) - 1)
            data_array[pos] = random.randint(0, 255)

        return bytes(data_array)


class ArithmeticMutator(Mutator):
    """Add or subtract small integers from integer fields"""

    DELTAS = [-128, -64, -32, -16, -8, -1, 1, 8, 16, 32, 64, 128]

    def mutate(self, data: bytes) -> bytes:
        if len(data) < 4:
            return data

        data_array = bytearray(data)
        # Pick a random 4-byte aligned position
        pos = random.randint(0, len(data) - 4)

        # Read as uint32, mutate, write back
        value = struct.unpack(">I", data_array[pos : pos + 4])[0]
        delta = random.choice(self.DELTAS)
        new_value = (value + delta) & 0xFFFFFFFF
        struct.pack_into(">I", data_array, pos, new_value)

        return bytes(data_array)


class InterestingValueMutator(Mutator):
    """
    Replace fields with "interesting" boundary values

    These values are known to trigger edge cases:
    - Integer boundaries (0, -1, MAX_INT, MAX_INT+1)
    - Powers of 2
    - Off-by-one values
    """

    INTERESTING_8 = [0, 1, 127, 128, 255]
    INTERESTING_16 = [0, 1, 255, 256, 32767, 32768, 65535]
    INTERESTING_32 = [0, 1, 65535, 65536, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]

    def mutate(self, data: bytes) -> bytes:
        if len(data) < 2:
            return data

        data_array = bytearray(data)
        pos = random.randint(0, len(data) - 2)

        # Choose size and interesting value
        if pos + 4 <= len(data) and random.random() < 0.5:
            # 32-bit value
            value = random.choice(self.INTERESTING_32)
            struct.pack_into(">I", data_array, pos, value)
        elif pos + 2 <= len(data):
            # 16-bit value
            value = random.choice(self.INTERESTING_16)
            struct.pack_into(">H", data_array, pos, value)
        else:
            # 8-bit value
            value = random.choice(self.INTERESTING_8)
            data_array[pos] = value

        return bytes(data_array)


class HavocMutator(Mutator):
    """
    Aggressive random mutations (havoc mode)

    Applies multiple random mutations in sequence:
    - Insert random bytes
    - Delete bytes
    - Duplicate chunks
    - Shuffle chunks
    """

    def mutate(self, data: bytes) -> bytes:
        if not data:
            return data

        data_array = bytearray(data)
        num_mutations = random.randint(2, 10)

        for _ in range(num_mutations):
            mutation_type = random.choice(["insert", "delete", "duplicate", "shuffle"])

            if mutation_type == "insert" and len(data_array) < 4096:
                # Insert random bytes
                pos = random.randint(0, len(data_array))
                insert_len = random.randint(1, 16)
                random_bytes = bytes(random.randint(0, 255) for _ in range(insert_len))
                data_array[pos:pos] = random_bytes

            elif mutation_type == "delete" and len(data_array) > 4:
                # Delete random bytes
                pos = random.randint(0, len(data_array) - 2)
                delete_len = random.randint(1, min(16, len(data_array) - pos))
                del data_array[pos : pos + delete_len]

            elif mutation_type == "duplicate" and len(data_array) > 4:
                # Duplicate a chunk
                start = random.randint(0, len(data_array) - 2)
                end = random.randint(start + 1, min(start + 32, len(data_array)))
                chunk = data_array[start:end]
                insert_pos = random.randint(0, len(data_array))
                data_array[insert_pos:insert_pos] = chunk

            elif mutation_type == "shuffle" and len(data_array) > 8:
                # Shuffle a chunk
                start = random.randint(0, len(data_array) - 4)
                end = random.randint(start + 4, min(start + 32, len(data_array)))
                chunk = list(data_array[start:end])
                random.shuffle(chunk)
                data_array[start:end] = chunk

        return bytes(data_array)


class SpliceMutator(Mutator):
    """Splice together parts of two different test cases"""

    def __init__(self, corpus: List[bytes]):
        self.corpus = corpus

    def mutate(self, data: bytes) -> bytes:
        if not self.corpus or len(self.corpus) < 2:
            return data

        other = random.choice(self.corpus)
        if other == data:
            alternatives = [s for s in self.corpus if s != data]
            if not alternatives:
                return data
            other = random.choice(alternatives)

        # Find splice points
        split1 = random.randint(0, len(data))
        split2 = random.randint(0, len(other))

        # Splice
        return data[:split1] + other[split2:]


class MutationEngine:
    """
    Orchestrates mutation strategies

    Supports hybrid mode combining structure-aware and byte-level mutations.
    """

    def __init__(
        self,
        seed_corpus: List[bytes],
        enabled_mutators: Optional[List[str]] = None,
        data_model: Optional[Dict[str, Any]] = None,
        mutation_mode: Optional[str] = None,
        structure_aware_weight: Optional[int] = None
    ):
        self.seed_corpus = seed_corpus
        self.data_model = data_model

        # Use session-level config if provided, otherwise fall back to global settings
        self.mutation_mode = mutation_mode if mutation_mode is not None else settings.mutation_mode
        self.structure_aware_weight = (
            structure_aware_weight if structure_aware_weight is not None
            else settings.structure_aware_weight
        )

        # Byte-level mutators (original implementation)
        self.mutators = {
            "bitflip": BitFlipMutator(),
            "byteflip": ByteFlipMutator(),
            "arithmetic": ArithmeticMutator(),
            "interesting": InterestingValueMutator(),
            "havoc": HavocMutator(),
            "splice": SpliceMutator(seed_corpus),
        }
        self.weights = {
            "bitflip": 20,
            "byteflip": 20,
            "arithmetic": 15,
            "interesting": 20,
            "havoc": 15,
            "splice": 10,
        }
        self.enabled_mutators = self._normalize_enabled(enabled_mutators)

        # Structure-aware mutator (NEW)
        self.structure_mutator = None
        if data_model and self.mutation_mode in ["structure_aware", "hybrid"]:
            try:
                from core.engine.structure_mutators import StructureAwareMutator
                self.structure_mutator = StructureAwareMutator(data_model)
                logger.info(
                    "structure_aware_mutation_enabled",
                    mode=self.mutation_mode,
                    weight=self.structure_aware_weight
                )
            except Exception as e:
                logger.error("failed_to_load_structure_mutator", error=str(e))
                self.structure_mutator = None

        self._last_metadata: Dict[str, Any] = {"strategy": None, "mutators": []}

    def _set_last_metadata(self, strategy: Optional[str], mutators: Optional[List[str]], field: Optional[str] = None) -> None:
        self._last_metadata = {
            "strategy": strategy,
            "mutators": list(mutators or []),
            "field": field,
        }

    def get_last_metadata(self) -> Dict[str, Any]:
        """Return metadata about the most recent mutation."""
        return {
            "strategy": self._last_metadata.get("strategy"),
            "mutators": list(self._last_metadata.get("mutators", [])),
            "field": self._last_metadata.get("field"),
        }

    def generate_test_case(self, base_seed: bytes, num_mutations: int = 1) -> bytes:
        """
        Generate a new test case by mutating a seed.

        Supports three modes:
        - structure_aware: Only use structure-aware mutations
        - byte_level: Only use byte-level mutations (original behavior)
        - hybrid: Mix both based on structure_aware_weight

        Args:
            base_seed: Seed to mutate
            num_mutations: Number of mutation passes to apply

        Returns:
            Mutated test case
        """
        # Determine which mutation approach to use
        use_structure_aware = False

        if self.mutation_mode == "structure_aware":
            use_structure_aware = self.structure_mutator is not None
        elif self.mutation_mode == "hybrid" and self.structure_mutator is not None:
            # Weighted random choice
            use_structure_aware = random.randint(1, 100) <= self.structure_aware_weight

        # Apply mutations
        if use_structure_aware:
            # Structure-aware mutation
            try:
                mutated = self.structure_mutator.mutate(base_seed)
                # Get the actual strategy and field that were applied
                strategy_used = self.structure_mutator.last_strategy or "unknown"
                field_mutated = self.structure_mutator.last_mutated_field
                self._set_last_metadata("structure_aware", [strategy_used], field=field_mutated)
                return mutated
            except Exception as e:
                logger.error("structure_mutation_failed", error=str(e))
                if not settings.fallback_on_parse_error:
                    self._set_last_metadata("structure_aware", ["parse_error_fallback"])
                    return base_seed
                # Fall through to byte-level

        # Byte-level mutation (original behavior)
        data = base_seed
        applied_mutators: List[str] = []
        for _ in range(num_mutations):
            mutator_name = random.choices(
                self.enabled_mutators,
                weights=[self.weights.get(name, 1) for name in self.enabled_mutators],
            )[0]

            mutator = self.mutators[mutator_name]
            data = mutator.mutate(data)
            applied_mutators.append(mutator_name)

        self._set_last_metadata("byte_level", applied_mutators)
        return data

    def generate_batch(self, count: int) -> List[bytes]:
        """Generate a batch of test cases"""
        test_cases = []
        for _ in range(count):
            seed = random.choice(self.seed_corpus)
            num_mutations = random.randint(1, 5)
            test_cases.append(self.generate_test_case(seed, num_mutations))
        return test_cases

    def _normalize_enabled(self, enabled: Optional[List[str]]) -> List[str]:
        available = list(self.mutators.keys())
        if not enabled:
            return available

        normalized = [name for name in enabled if name in self.mutators]
        if not normalized:
            logger.warning("mutator_fallback", enabled=enabled)
            return available
        return normalized

    @staticmethod
    def available_mutators() -> List[str]:
        """
        Return list of available byte-level mutator names.

        These are the mutation algorithms that can be enabled/disabled
        via the `enabled_mutators` session config:
        - bitflip: Flip random bits in the input
        - byteflip: Replace random bytes with random values
        - arithmetic: Add/subtract small integers from fields
        - interesting: Replace with boundary values (0, MAX_INT, etc.)
        - havoc: Aggressive random mutations (insert, delete, shuffle)
        - splice: Combine parts of two different test cases

        Note: Structure-aware mutation is controlled separately via
        `mutation_mode` (byte_level, structure_aware, hybrid) and
        `structure_aware_weight`, not via this list.
        """
        return ["bitflip", "byteflip", "arithmetic", "interesting", "havoc", "splice"]
