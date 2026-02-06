"""
Enumeration Generator - Systematic test case generation

Generates test cases that systematically cover boundary values for each mutable field.
Unlike random mutation, this produces a deterministic, finite set of test cases
that provides comprehensive coverage of edge cases.

MODES:
======
- field_sweep: Test each field independently through all boundary values
  (Total tests = sum of boundary values per field, typically ~5 per field)

- pairwise: Test all pairs of boundary values across fields
  (Total tests = n^2 where n is number of fields × values, can be large)

- full_permutation: Test all combinations (WARNING: combinatorial explosion!)
  (Only practical for protocols with very few mutable fields)

USAGE:
======
    generator = EnumerationGenerator(data_model)

    # Get count for progress tracking
    total = generator.get_total_tests(mode="field_sweep")

    # Generate all test cases
    for test_case in generator.generate(mode="field_sweep"):
        # test_case is bytes ready to send
        pass

The generated test cases use default values for all fields except the ones
being enumerated, ensuring message validity.
"""
from typing import Any, Dict, Generator, List, Optional, Tuple
from itertools import product, combinations

import structlog

from core.engine.protocol_parser import ProtocolParser
from core.engine.mutation_primitives import generate_boundary_values, INTERESTING_VALUES

logger = structlog.get_logger()


class EnumerationGenerator:
    """
    Generates systematic test cases for boundary value coverage.

    Produces deterministic test cases that cover boundary values
    for each mutable field in the protocol.
    """

    def __init__(self, data_model: Dict[str, Any]):
        """
        Initialize enumeration generator.

        Args:
            data_model: Protocol data model with 'blocks' list
        """
        self.data_model = data_model
        self.parser = ProtocolParser(data_model)
        self.blocks = data_model.get('blocks', [])

        # Pre-compute mutable fields and their boundary values
        self._mutable_fields: List[Dict[str, Any]] = []
        self._field_values: Dict[str, List[Any]] = {}
        self._analyze_fields()

    def _analyze_fields(self) -> None:
        """Analyze data_model to identify mutable fields and their boundary values."""
        for block in self.blocks:
            name = block.get('name', '')
            field_type = block.get('type', '')

            # Skip non-mutable fields
            if not block.get('mutable', True):
                continue

            # Skip size fields and dependent fields
            if block.get('is_size_field') or block.get('size_of'):
                continue

            # Generate boundary values based on field type
            values = self._get_field_values(block)

            if values:
                self._mutable_fields.append(block)
                self._field_values[name] = values
                logger.debug(
                    "enumeration_field_analyzed",
                    field=name,
                    type=field_type,
                    num_values=len(values)
                )

    def _get_field_values(self, block: Dict[str, Any]) -> List[Any]:
        """
        Get enumeration values for a field.

        Combines:
        - Boundary values (0, 1, max-1, max, etc.)
        - Enum values (if 'values' dict defined)
        - Interesting values (powers of 2, etc.)

        Args:
            block: Field block definition

        Returns:
            List of values to test for this field
        """
        field_type = block.get('type', '')
        values = set()

        # Add boundary values for numeric types
        if field_type in ('uint8', 'uint16', 'uint32', 'uint64',
                          'int8', 'int16', 'int32', 'int64', 'bits'):
            boundary = generate_boundary_values(block)
            values.update(boundary)

        # Add enum values if defined
        if 'values' in block:
            enum_values = block['values']
            if isinstance(enum_values, dict):
                values.update(enum_values.keys())
            elif isinstance(enum_values, list):
                values.update(enum_values)

        # Add default value
        if 'default' in block:
            default = block['default']
            if isinstance(default, int):
                values.add(default)

        # For bytes fields, generate size variants
        if field_type == 'bytes':
            max_size = block.get('max_size', block.get('size', 256))
            fixed_size = block.get('size')

            if fixed_size:
                # Fixed size - just use zeros and ones
                values = [
                    b'\x00' * fixed_size,
                    b'\xff' * fixed_size,
                    b'\x41' * fixed_size,  # 'AAA...'
                ]
            else:
                # Variable size - test different lengths
                values = [
                    b'',  # Empty
                    b'\x00',  # Single null
                    b'\x41',  # Single 'A'
                    b'\x00' * min(max_size, 256),  # Zeros up to max
                    b'\xff' * min(max_size, 256),  # Ones up to max
                ]
            return list(values)

        # For string fields
        if field_type == 'string':
            max_size = block.get('max_size', block.get('size', 256))
            return [
                '',  # Empty
                'A',  # Single char
                'A' * min(max_size, 256),  # Max length
                '\x00',  # Null char
            ]

        return sorted(values) if values else []

    def get_mutable_fields(self) -> List[str]:
        """Return list of mutable field names."""
        return [b.get('name', '') for b in self._mutable_fields]

    def get_field_value_count(self, field_name: str) -> int:
        """Return number of enumeration values for a field."""
        return len(self._field_values.get(field_name, []))

    def get_total_tests(self, mode: str = "field_sweep") -> int:
        """
        Calculate total number of test cases that will be generated.

        Args:
            mode: Enumeration mode ("field_sweep", "pairwise", "full_permutation")

        Returns:
            Total number of test cases
        """
        if not self._mutable_fields:
            return 0

        if mode == "field_sweep":
            # Sum of values per field
            return sum(len(v) for v in self._field_values.values())

        elif mode == "pairwise":
            # For each pair of fields, product of their value counts
            fields = list(self._field_values.keys())
            total = 0
            for i, f1 in enumerate(fields):
                for f2 in fields[i+1:]:
                    total += len(self._field_values[f1]) * len(self._field_values[f2])
            # Also include single-field coverage
            total += sum(len(v) for v in self._field_values.values())
            return total

        elif mode == "full_permutation":
            # Product of all value counts (WARNING: can be huge!)
            total = 1
            for values in self._field_values.values():
                total *= len(values)
            return total

        return 0

    def generate(self, mode: str = "field_sweep") -> Generator[Tuple[bytes, Dict[str, Any]], None, None]:
        """
        Generate test cases systematically.

        Args:
            mode: Enumeration mode

        Yields:
            Tuple of (test_case_bytes, metadata_dict)
            metadata includes: field_name, value, mode, index
        """
        if mode == "field_sweep":
            yield from self._generate_field_sweep()
        elif mode == "pairwise":
            yield from self._generate_pairwise()
        elif mode == "full_permutation":
            yield from self._generate_full_permutation()
        else:
            logger.warning("unknown_enumeration_mode", mode=mode)
            yield from self._generate_field_sweep()

    def _build_default_fields(self) -> Dict[str, Any]:
        """Build field dictionary with default values."""
        fields = {}
        for block in self.blocks:
            name = block.get('name', '')
            if 'default' in block:
                fields[name] = block['default']
            else:
                fields[name] = self._get_minimal_value(block)
        return fields

    def _get_minimal_value(self, block: Dict[str, Any]) -> Any:
        """Get minimal valid value for a field."""
        field_type = block.get('type', '')

        if field_type.startswith('uint') or field_type.startswith('int') or field_type == 'bits':
            if 'values' in block:
                return list(block['values'].keys())[0]
            return 0
        elif field_type == 'bytes':
            size = block.get('size', 0)
            return b'\x00' * size if size > 0 else b''
        elif field_type == 'string':
            return ''
        return None

    def _generate_field_sweep(self) -> Generator[Tuple[bytes, Dict[str, Any]], None, None]:
        """
        Generate test cases varying one field at a time.

        For each mutable field, generates tests with each boundary value
        while keeping all other fields at their defaults.
        """
        index = 0

        for block in self._mutable_fields:
            field_name = block.get('name', '')
            values = self._field_values.get(field_name, [])

            for value in values:
                try:
                    fields = self._build_default_fields()
                    fields[field_name] = value

                    test_case = self.parser.serialize(fields)

                    metadata = {
                        "mode": "field_sweep",
                        "field": field_name,
                        "value": value if not isinstance(value, bytes) else value.hex(),
                        "index": index,
                    }

                    yield test_case, metadata
                    index += 1

                except Exception as e:
                    logger.warning(
                        "enumeration_serialize_failed",
                        field=field_name,
                        value=str(value)[:50],
                        error=str(e)
                    )

    def _generate_pairwise(self) -> Generator[Tuple[bytes, Dict[str, Any]], None, None]:
        """
        Generate test cases covering all pairs of field values.

        First does single-field coverage, then all pairs.
        """
        index = 0

        # First: single-field coverage
        for test_case, metadata in self._generate_field_sweep():
            metadata["mode"] = "pairwise_single"
            metadata["index"] = index
            yield test_case, metadata
            index += 1

        # Then: pairwise combinations
        field_names = list(self._field_values.keys())

        for i, field1 in enumerate(field_names):
            for field2 in field_names[i+1:]:
                values1 = self._field_values[field1]
                values2 = self._field_values[field2]

                for v1, v2 in product(values1, values2):
                    try:
                        fields = self._build_default_fields()
                        fields[field1] = v1
                        fields[field2] = v2

                        test_case = self.parser.serialize(fields)

                        metadata = {
                            "mode": "pairwise",
                            "fields": [field1, field2],
                            "values": [
                                v1 if not isinstance(v1, bytes) else v1.hex(),
                                v2 if not isinstance(v2, bytes) else v2.hex(),
                            ],
                            "index": index,
                        }

                        yield test_case, metadata
                        index += 1

                    except Exception as e:
                        logger.warning(
                            "pairwise_serialize_failed",
                            fields=[field1, field2],
                            error=str(e)
                        )

    def _generate_full_permutation(self) -> Generator[Tuple[bytes, Dict[str, Any]], None, None]:
        """
        Generate ALL combinations of all field values.

        WARNING: This can produce an enormous number of test cases!
        Use with caution on protocols with many mutable fields.
        """
        if not self._mutable_fields:
            return

        field_names = [b.get('name', '') for b in self._mutable_fields]
        value_lists = [self._field_values[name] for name in field_names]

        total = self.get_total_tests("full_permutation")
        if total > 100000:
            logger.warning(
                "full_permutation_large",
                total_tests=total,
                hint="Consider using 'field_sweep' or 'pairwise' mode instead"
            )

        index = 0
        for combination in product(*value_lists):
            try:
                fields = self._build_default_fields()

                for name, value in zip(field_names, combination):
                    fields[name] = value

                test_case = self.parser.serialize(fields)

                metadata = {
                    "mode": "full_permutation",
                    "fields": field_names,
                    "values": [
                        v if not isinstance(v, bytes) else v.hex()
                        for v in combination
                    ],
                    "index": index,
                }

                yield test_case, metadata
                index += 1

            except Exception as e:
                logger.warning(
                    "permutation_serialize_failed",
                    index=index,
                    error=str(e)
                )


def get_enumeration_count(data_model: Dict[str, Any], mode: str = "field_sweep") -> int:
    """
    Convenience function to get test count without generating.

    Args:
        data_model: Protocol data model
        mode: Enumeration mode

    Returns:
        Total number of test cases that would be generated
    """
    generator = EnumerationGenerator(data_model)
    return generator.get_total_tests(mode)


def generate_enumeration_tests(
    data_model: Dict[str, Any],
    mode: str = "field_sweep"
) -> Generator[Tuple[bytes, Dict[str, Any]], None, None]:
    """
    Convenience function to generate enumeration test cases.

    Args:
        data_model: Protocol data model
        mode: Enumeration mode ("field_sweep", "pairwise", "full_permutation")

    Yields:
        Tuple of (test_case_bytes, metadata_dict)
    """
    generator = EnumerationGenerator(data_model)
    yield from generator.generate(mode)
