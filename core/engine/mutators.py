"""
Mutation strategies for test case generation

Implements various mutation strategies from the blueprint:
- Bit flipping
- Byte flipping
- Arithmetic mutations
- Interesting values (boundary values)
- Havoc (random heavy mutations)
"""
import random
import struct
from typing import List

import structlog

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

        # Pick another seed
        other = random.choice([s for s in self.corpus if s != data])
        if not other:
            return data

        # Find splice points
        split1 = random.randint(0, len(data))
        split2 = random.randint(0, len(other))

        # Splice
        return data[:split1] + other[split2:]


class MutationEngine:
    """
    Orchestrates mutation strategies

    Selects and applies appropriate mutators based on configuration
    """

    def __init__(self, seed_corpus: List[bytes]):
        self.seed_corpus = seed_corpus
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

    def generate_test_case(self, base_seed: bytes, num_mutations: int = 1) -> bytes:
        """
        Generate a new test case by mutating a seed

        Args:
            base_seed: Seed to mutate
            num_mutations: Number of mutation passes to apply

        Returns:
            Mutated test case
        """
        data = base_seed

        for _ in range(num_mutations):
            # Select mutator based on weights
            mutator_name = random.choices(
                list(self.mutators.keys()), weights=list(self.weights.values())
            )[0]

            mutator = self.mutators[mutator_name]
            data = mutator.mutate(data)

        return data

    def generate_batch(self, count: int) -> List[bytes]:
        """Generate a batch of test cases"""
        test_cases = []
        for _ in range(count):
            seed = random.choice(self.seed_corpus)
            num_mutations = random.randint(1, 5)
            test_cases.append(self.generate_test_case(seed, num_mutations))
        return test_cases
