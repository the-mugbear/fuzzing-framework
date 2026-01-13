"""
Shared Mutation Primitives

Common mutation operations used by both byte-level and structure-aware mutators.
Consolidates duplicate logic to ensure consistent behavior.
"""
import random
from typing import Any, Dict, List, Optional


# Arithmetic mutation deltas
ARITHMETIC_DELTAS = [-128, -64, -32, -16, -8, -4, -2, -1, 1, 2, 4, 8, 16, 32, 64, 128]

# Interesting boundary values for different bit widths
INTERESTING_VALUES = {
    8: [0, 1, 127, 128, 255],
    16: [0, 1, 255, 256, 32767, 32768, 65535],
    32: [0, 1, 65535, 65536, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF],
    64: [0, 1, 0xFFFFFFFF, 0x100000000, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000, 0xFFFFFFFFFFFFFFFF],
}


def apply_arithmetic_mutation(value: int, field_info: Optional[Dict] = None) -> int:
    """
    Apply arithmetic mutation by adding/subtracting a delta.

    Args:
        value: Original integer value
        field_info: Optional field metadata (for clamping to field max)

    Returns:
        Mutated integer value
    """
    delta = random.choice(ARITHMETIC_DELTAS)
    new_value = value + delta

    # Clamp to field size if provided
    if field_info:
        field_type = field_info.get("type", "")
        if field_type == "bits":
            num_bits = field_info.get("size", 32)
            max_value = (1 << num_bits) - 1
            new_value = new_value & max_value
        elif field_type.startswith("uint"):
            # Extract bit width from type name
            bit_width = _extract_bit_width(field_type)
            max_value = (1 << bit_width) - 1
            new_value = new_value & max_value
        elif field_type.startswith("int"):
            # Signed integer handling
            bit_width = _extract_bit_width(field_type)
            max_value = (1 << (bit_width - 1)) - 1
            min_value = -(1 << (bit_width - 1))
            new_value = max(min_value, min(max_value, new_value))

    return new_value


def select_interesting_value(field_info: Optional[Dict] = None, bit_width: Optional[int] = None) -> int:
    """
    Select an interesting boundary value for testing.

    Args:
        field_info: Optional field metadata
        bit_width: Optional explicit bit width (overrides field_info)

    Returns:
        Interesting boundary value
    """
    # Determine bit width
    if bit_width is None:
        if field_info:
            field_type = field_info.get("type", "")
            if field_type == "bits":
                bit_width = field_info.get("size", 32)
            elif field_type.startswith("uint") or field_type.startswith("int"):
                bit_width = _extract_bit_width(field_type)
            else:
                bit_width = 32  # Default
        else:
            bit_width = 32  # Default

    # Select from appropriate interesting values list
    if bit_width <= 8:
        values = INTERESTING_VALUES[8]
    elif bit_width <= 16:
        values = INTERESTING_VALUES[16]
    elif bit_width <= 32:
        values = INTERESTING_VALUES[32]
    else:
        values = INTERESTING_VALUES[64]

    value = random.choice(values)

    # Clamp to actual bit width
    max_value = (1 << bit_width) - 1
    return value & max_value


def generate_boundary_values(field_info: Dict) -> List[int]:
    """
    Generate comprehensive boundary values for a field.

    Args:
        field_info: Field metadata dictionary

    Returns:
        List of boundary values to test
    """
    field_type = field_info.get("type", "")
    boundary_values = []

    if field_type == "bits":
        num_bits = field_info.get("size", 32)
        max_value = (1 << num_bits) - 1

        boundary_values = [
            0,  # Minimum
            1,  # Minimum + 1
            max_value // 2,  # Middle
            max_value - 1,  # Maximum - 1
            max_value,  # Maximum
        ]

    elif field_type.startswith("uint"):
        bit_width = _extract_bit_width(field_type)
        max_value = (1 << bit_width) - 1

        boundary_values = [
            0,  # Min
            1,  # Min + 1
            max_value // 2,  # Mid
            max_value - 1,  # Max - 1
            max_value,  # Max
        ]

    elif field_type.startswith("int"):
        bit_width = _extract_bit_width(field_type)
        max_value = (1 << (bit_width - 1)) - 1
        min_value = -(1 << (bit_width - 1))

        boundary_values = [
            min_value,  # Min (most negative)
            min_value + 1,  # Min + 1
            -1,  # -1
            0,  # Zero
            1,  # +1
            max_value - 1,  # Max - 1
            max_value,  # Max (most positive)
        ]

    return boundary_values


def flip_random_bits(value: int, num_bits: int, num_flips: int = 1) -> int:
    """
    Flip random bits in a value.

    Args:
        value: Original value
        num_bits: Total number of bits in the value
        num_flips: Number of bits to flip

    Returns:
        Value with flipped bits
    """
    for _ in range(num_flips):
        bit_pos = random.randint(0, num_bits - 1)
        value ^= (1 << bit_pos)

    # Mask to bit width
    mask = (1 << num_bits) - 1
    return value & mask


def generate_power_of_two_pattern(num_bits: int) -> int:
    """
    Generate a power-of-2 bit pattern (single bit set).

    Args:
        num_bits: Number of bits in the field

    Returns:
        Value with single bit set
    """
    bit_pos = random.randint(0, num_bits - 1)
    return 1 << bit_pos


def _extract_bit_width(field_type: str) -> int:
    """
    Extract bit width from field type string.

    Args:
        field_type: Type string like "uint32", "int16", etc.

    Returns:
        Bit width (8, 16, 32, or 64)
    """
    if "8" in field_type:
        return 8
    elif "16" in field_type:
        return 16
    elif "32" in field_type:
        return 32
    elif "64" in field_type:
        return 64
    else:
        return 32  # Default
