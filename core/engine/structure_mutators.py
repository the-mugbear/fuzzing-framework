"""
Structure-Aware Mutation Engine

Mutates protocol messages intelligently using data_model specification.
Maintains message validity by respecting field types and auto-fixing dependent fields.
"""
import random
from typing import Any, Dict, List, Optional

import structlog

from core.engine.protocol_parser import ProtocolParser

logger = structlog.get_logger()


class StructureAwareMutator:
    """
    Structure-aware mutation engine.

    Uses data_model to mutate fields intelligently while maintaining
    message validity (auto-fixing lengths, checksums, etc.).

    Single mutator class with strategy methods that adapt based on
    field metadata rather than separate classes per type.
    """

    # Mutation strategies and their weights
    STRATEGIES = {
        "boundary_values": 25,
        "arithmetic": 20,
        "bit_flip_field": 15,
        "interesting_values": 20,
        "expand_field": 8,
        "shrink_field": 7,
        "repeat_pattern": 5,
    }

    def __init__(self, data_model: Dict[str, Any]):
        """
        Initialize structure-aware mutator.

        Args:
            data_model: Protocol definition with 'blocks' list
        """
        self.data_model = data_model
        self.parser = ProtocolParser(data_model)
        self.blocks = data_model.get('blocks', [])

        # Build weighted strategy list
        self.strategy_list = []
        for strategy, weight in self.STRATEGIES.items():
            self.strategy_list.extend([strategy] * weight)

        # Track last applied strategy and field for metadata
        self.last_strategy: Optional[str] = None
        self.last_mutated_field: Optional[str] = None

    def mutate(self, seed: bytes) -> bytes:
        """
        Generate mutated test case from seed.

        Args:
            seed: Base seed message

        Returns:
            Mutated message bytes
        """
        try:
            # 1. Parse message into structured fields
            fields = self.parser.parse(seed)

            # 2. Select a mutable field to mutate
            mutable_fields = self._get_mutable_fields()
            if not mutable_fields:
                logger.warning("no_mutable_fields", data_model=self.data_model.get('name'))
                return seed

            target_block = random.choice(mutable_fields)
            field_name = target_block['name']

            # 3. Select and apply mutation strategy
            strategy = random.choice(self.strategy_list)
            self.last_strategy = strategy  # Track for metadata
            self.last_mutated_field = field_name  # Track which field was mutated
            original_value = fields[field_name]

            try:
                mutated_value = self._apply_strategy(
                    strategy,
                    original_value,
                    target_block
                )
                fields[field_name] = mutated_value

                logger.debug(
                    "field_mutated",
                    field=field_name,
                    strategy=strategy,
                    original_type=type(original_value).__name__,
                    mutated_type=type(mutated_value).__name__,
                )

            except Exception as e:
                logger.error(
                    "mutation_strategy_failed",
                    strategy=strategy,
                    field=field_name,
                    error=str(e)
                )
                # Fall back to original value
                pass

            # 4. Serialize back to bytes (auto-fixes lengths, checksums)
            return self.parser.serialize(fields)

        except Exception as e:
            logger.error("structure_mutation_failed", error=str(e))
            # Fall back to returning original seed
            return seed

    def _apply_strategy(
        self,
        strategy: str,
        value: Any,
        block: dict
    ) -> Any:
        """
        Apply mutation strategy to field value.

        Args:
            strategy: Strategy name
            value: Current field value
            block: Field specification from data_model

        Returns:
            Mutated value
        """
        strategy_method = {
            "boundary_values": self._boundary_values,
            "arithmetic": self._arithmetic,
            "bit_flip_field": self._bit_flip_field,
            "interesting_values": self._interesting_values,
            "expand_field": self._expand_field,
            "shrink_field": self._shrink_field,
            "repeat_pattern": self._repeat_pattern,
        }

        method = strategy_method.get(strategy)
        if method:
            return method(value, block)
        else:
            return value

    def _boundary_values(self, value: Any, block: dict) -> Any:
        """
        Test boundary conditions based on field type.

        For integers: 0, 1, MAX, MIN
        For bytes: empty, single byte, max_size
        For bits: 0, 1, MAX, MAX-1, mid
        """
        field_type = block['type']

        if field_type == 'bits':
            # Bit field boundaries
            num_bits = block['size']
            max_val = (1 << num_bits) - 1

            candidates = [
                0,           # Min
                1,           # Min + 1
                max_val // 2,  # Mid
                max_val - 1,   # Max - 1
                max_val        # Max
            ]
            # Remove duplicates and invalid values
            candidates = [v for v in set(candidates) if 0 <= v <= max_val]
            return random.choice(candidates)

        if 'int' in field_type:
            # Integer boundaries
            if field_type == 'uint8':
                return random.choice([0, 1, 127, 128, 254, 255])
            elif field_type == 'uint16':
                return random.choice([0, 1, 255, 256, 32767, 32768, 65534, 65535])
            elif field_type == 'uint32':
                return random.choice([0, 1, 65535, 65536, 0x7FFFFFFF, 0xFFFFFFFE, 0xFFFFFFFF])
            elif field_type == 'uint64':
                return random.choice([0, 1, 0xFFFFFFFF, 0x100000000, 0x7FFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF])
            elif field_type == 'int8':
                return random.choice([-128, -1, 0, 1, 126, 127])
            elif field_type == 'int16':
                return random.choice([-32768, -1, 0, 1, 32766, 32767])
            elif field_type == 'int32':
                return random.choice([-2147483648, -1, 0, 1, 2147483646, 2147483647])

        elif field_type == 'bytes':
            # Byte array boundaries
            max_size = block.get('max_size', 1024)
            choices = [
                b'',  # Empty
                b'\x00',  # Single null byte
                b'\xFF',  # Single max byte
                b'\x00' * max_size,  # Max size nulls
                b'\xFF' * max_size,  # Max size 0xFF
                b'A' * (max_size - 1),  # Max size - 1
                b'A' * (max_size + 1),  # Max size + 1 (will be truncated)
            ]
            return random.choice(choices)

        return value

    def _arithmetic(self, value: Any, block: dict) -> Any:
        """
        Apply arithmetic mutations (add/subtract small values).

        Only applicable to integer and bit fields.
        """
        field_type = block['type']

        if field_type == 'bits':
            # Arithmetic for bit fields
            num_bits = block['size']
            max_val = (1 << num_bits) - 1

            if not isinstance(value, int):
                return value

            operations = [
                value + 1,
                value - 1,
                value + random.randint(1, 5),
                value - random.randint(1, 5),
                value ^ 1,  # Flip LSB
            ]

            # Clamp to valid range with wraparound
            mutated = random.choice(operations)
            return mutated & max_val

        if 'int' not in field_type:
            return value  # Not applicable

        # Arithmetic deltas
        deltas = [-256, -128, -16, -1, 1, 16, 128, 256]
        delta = random.choice(deltas)

        # Apply delta with wraparound
        if field_type == 'uint8':
            return (value + delta) & 0xFF
        elif field_type == 'uint16':
            return (value + delta) & 0xFFFF
        elif field_type == 'uint32':
            return (value + delta) & 0xFFFFFFFF
        elif field_type == 'uint64':
            return (value + delta) & 0xFFFFFFFFFFFFFFFF
        elif field_type.startswith('int'):
            # Signed integers - let Python handle it
            return value + delta

        return value

    def _bit_flip_field(self, value: Any, block: dict) -> Any:
        """
        Flip random bits in field value.

        Works on integers and byte arrays.
        """
        field_type = block['type']

        if 'int' in field_type:
            # Flip random bit in integer
            if field_type == 'uint8' or field_type == 'int8':
                bit_pos = random.randint(0, 7)
            elif field_type == 'uint16' or field_type == 'int16':
                bit_pos = random.randint(0, 15)
            elif field_type == 'uint32' or field_type == 'int32':
                bit_pos = random.randint(0, 31)
            else:  # uint64/int64
                bit_pos = random.randint(0, 63)

            return value ^ (1 << bit_pos)

        elif field_type == 'bytes' and value:
            # Flip random bit in byte array
            value_array = bytearray(value)
            byte_pos = random.randint(0, len(value_array) - 1)
            bit_pos = random.randint(0, 7)
            value_array[byte_pos] ^= (1 << bit_pos)
            return bytes(value_array)

        return value

    def _interesting_values(self, value: Any, block: dict) -> Any:
        """
        Replace with interesting/magic values.

        Uses known values from data_model if available.
        """
        field_type = block['type']

        # Check if block defines known values
        if 'values' in block:
            known_values = list(block['values'].keys())
            if known_values:
                # Use a known value or adjacent value
                if random.random() < 0.7:
                    return random.choice(known_values)
                else:
                    # Adjacent to known value
                    base = random.choice(known_values)
                    return base + random.choice([-1, 1])

        # Generic interesting values by type
        if field_type == 'bits':
            # Bit field interesting values
            num_bits = block['size']
            max_val = (1 << num_bits) - 1

            interesting = [
                0x0,                    # All zeros
                0x1,                    # Single bit
                max_val,                # All ones
                (1 << (num_bits - 1)),  # MSB only
            ]

            # Add power-of-2 values within range
            for i in range(num_bits):
                interesting.append(1 << i)

            # Filter to valid range and remove duplicates
            interesting = [v for v in set(interesting) if 0 <= v <= max_val]
            return random.choice(interesting)

        if field_type == 'uint8':
            return random.choice([0, 1, 0x7F, 0x80, 0xFF])
        elif field_type == 'uint16':
            return random.choice([0, 1, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFF])
        elif field_type == 'uint32':
            return random.choice([0, 1, 0xFFFF, 0x10000, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF])
        elif field_type == 'bytes':
            # Interesting byte patterns
            patterns = [
                b'\x00\x00\x00\x00',
                b'\xFF\xFF\xFF\xFF',
                b'\xDE\xAD\xBE\xEF',
                b'%s%s%n',
                b'../../../etc/passwd',
                b"' OR 1=1--",
            ]
            return random.choice(patterns)

        return value

    def _expand_field(self, value: Any, block: dict) -> Any:
        """
        Expand field size (for variable-length fields).
        """
        field_type = block['type']

        if field_type == 'bytes':
            max_size = block.get('max_size', 1024)
            current_len = len(value) if value else 0

            # Expand by 1.5x to 3x
            expansion_factor = random.uniform(1.5, 3.0)
            new_len = min(int(current_len * expansion_factor), max_size)

            if new_len > current_len:
                # Extend with repeated pattern
                if value:
                    repeat_pattern = value
                else:
                    repeat_pattern = b'A'

                return (repeat_pattern * (new_len // len(repeat_pattern) + 1))[:new_len]

        return value

    def _shrink_field(self, value: Any, block: dict) -> Any:
        """
        Shrink field size (for variable-length fields).
        """
        field_type = block['type']

        if field_type == 'bytes' and value:
            current_len = len(value)
            if current_len > 1:
                # Shrink to 10%-50% of current size
                shrink_factor = random.uniform(0.1, 0.5)
                new_len = max(0, int(current_len * shrink_factor))
                return value[:new_len]

        return value

    def _repeat_pattern(self, value: Any, block: dict) -> Any:
        """
        Fill field with repeating pattern.
        """
        field_type = block['type']

        if field_type == 'bytes':
            max_size = block.get('max_size', 1024)

            # Choose pattern
            patterns = [
                b'\x00',
                b'\xFF',
                b'A',
                b'%s',
                b'\x90',  # NOP sled
                b'\xCC',  # INT3 (debugger breakpoint)
            ]
            pattern = random.choice(patterns)

            # Fill to random size
            size = random.randint(1, max_size)
            return pattern * size

        return value

    def _get_mutable_fields(self) -> List[dict]:
        """
        Get list of fields that can be mutated.

        Respects 'mutable' flag in block definition.
        """
        mutable = []
        for block in self.blocks:
            if block.get('mutable', True):  # Default to mutable
                mutable.append(block)
        return mutable
