"""
Structure-Aware Mutation Engine

Mutates protocol messages intelligently using data_model specification.
Maintains message validity by respecting field types and auto-fixing dependent fields.
"""
import random
from typing import Any, Dict, List, Optional

import structlog

from core.config import settings
from core.engine.protocol_parser import ProtocolParser
from core.engine.mutation_primitives import (
    apply_arithmetic_mutation,
    select_interesting_value,
    generate_boundary_values,
    flip_random_bits,
)

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

    # Mapping from byte-level mutator names to structure-aware strategies
    # This allows users to select familiar mutator names and have them
    # applied in a structure-aware manner
    MUTATOR_TO_STRATEGY = {
        "bitflip": ["bit_flip_field"],
        "byteflip": ["bit_flip_field"],  # Byte flip = bit flips at field level
        "arithmetic": ["arithmetic"],
        "interesting": ["interesting_values", "boundary_values"],
        "havoc": ["expand_field", "shrink_field", "repeat_pattern"],
        "splice": [],  # No direct equivalent - requires multiple seeds
    }

    def __init__(self, data_model: Dict[str, Any], enabled_mutators: Optional[List[str]] = None):
        """
        Initialize structure-aware mutator.

        Args:
            data_model: Protocol definition with 'blocks' list
            enabled_mutators: Optional list of mutator names to enable.
                             Maps to structure-aware strategies via MUTATOR_TO_STRATEGY.
                             If None or empty, all strategies are enabled.
        """
        self.data_model = data_model
        self.parser = ProtocolParser(data_model)
        self.blocks = data_model.get('blocks', [])

        # Determine which strategies to enable based on mutator selection
        enabled_strategies = self._resolve_strategies(enabled_mutators)

        # Build weighted strategy list (only enabled strategies)
        self.strategy_list = []
        for strategy, weight in self.STRATEGIES.items():
            if strategy in enabled_strategies:
                self.strategy_list.extend([strategy] * weight)

        # Fallback: if no strategies enabled, use all
        if not self.strategy_list:
            for strategy, weight in self.STRATEGIES.items():
                self.strategy_list.extend([strategy] * weight)
            logger.warning(
                "structure_mutator_no_strategies_matched",
                enabled_mutators=enabled_mutators,
                using="all_strategies"
            )

        # Track last applied strategy and field for metadata
        self.last_strategy: Optional[str] = None
        self.last_mutated_field: Optional[str] = None

    def _resolve_strategies(self, enabled_mutators: Optional[List[str]]) -> set:
        """
        Convert byte-level mutator names to structure-aware strategies.

        Args:
            enabled_mutators: List of mutator names (bitflip, arithmetic, etc.)

        Returns:
            Set of enabled strategy names
        """
        if not enabled_mutators:
            # No filter - enable all strategies
            return set(self.STRATEGIES.keys())

        strategies = set()
        for mutator in enabled_mutators:
            mapped = self.MUTATOR_TO_STRATEGY.get(mutator, [])
            strategies.update(mapped)

        return strategies if strategies else set(self.STRATEGIES.keys())

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
                    error=str(e),
                    error_type=type(e).__name__
                )
                # Fall back to original value - continue with unmutated field

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
        Test boundary conditions using shared primitives.

        For integers/bits: Uses generate_boundary_values()
        For bytes: Uses custom byte array logic
        """
        field_type = block['type']

        if field_type == 'bits' or 'int' in field_type:
            # Use shared primitive for consistent boundary values
            candidates = generate_boundary_values(block)
            if candidates:
                return random.choice(candidates)
            return value

        elif field_type == 'bytes':
            # Byte array boundaries (field-specific logic)
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
        Apply arithmetic mutations using shared primitives.

        Only applicable to integer and bit fields.
        """
        field_type = block['type']

        if field_type == 'bits' or 'int' in field_type:
            if not isinstance(value, int):
                return value
            # Use shared primitive for consistent behavior
            return apply_arithmetic_mutation(value, block)

        return value  # Not applicable

    def _bit_flip_field(self, value: Any, block: dict) -> Any:
        """
        Flip random bits in field value.

        Works on integers, byte arrays, and bit fields.
        """
        field_type = block['type']

        if field_type == 'bits':
            # Flip random bit in sub-byte bit field
            num_bits = block.get('size', 1)
            if num_bits > 0:
                bit_pos = random.randint(0, num_bits - 1)
                return value ^ (1 << bit_pos)

        elif 'int' in field_type:
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
        Replace with interesting/magic values using shared primitives.

        Uses known values from data_model if available, otherwise
        uses shared select_interesting_value() primitive.
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

        # Use shared primitive for consistent interesting values
        if field_type == 'bits' or 'int' in field_type:
            return select_interesting_value(field_info=block)

        if field_type == 'bytes':
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

            # Expand by configurable factor
            expansion_factor = random.uniform(
                settings.havoc_expansion_min,
                settings.havoc_expansion_max
            )
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
