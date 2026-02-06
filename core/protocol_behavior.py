"""
Protocol Behavior Processor - Runtime Field Manipulation for Protocol Plugins
==============================================================================

This module provides the BehaviorProcessor class which applies declarative behaviors
defined in protocol plugin data models. Behaviors allow fields to be automatically
modified at runtime without explicit fuzzer intervention.

SUPPORTED BEHAVIORS:
====================

1. INCREMENT - Auto-incrementing sequence numbers
   Example: {"operation": "increment", "initial": 1, "step": 1, "wrap": 65536}
   Use case: Protocol sequence counters, message IDs

2. ADD_CONSTANT - Add a fixed value to a field
   Example: {"operation": "add_constant", "value": 100}
   Use case: Offsets, checksums that need adjustment

BEHAVIOR DEFINITION IN DATA MODEL:
==================================

Behaviors are defined on individual blocks in the data model:

    {
        "name": "sequence_number",
        "type": "uint16",
        "endian": "big",
        "behavior": {
            "operation": "increment",
            "initial": 0,
            "step": 1,
            "wrap": 65536
        }
    }

BIT FIELD SUPPORT:
==================

The BehaviorProcessor correctly handles protocols that mix bit fields (sub-byte)
with byte-aligned fields. It tracks positions in bits internally and converts
to byte offsets when manipulating the buffer.

USAGE:
======

    processor = BehaviorProcessor(data_model)
    state = processor.initialize_state()

    # Apply behaviors to each test case
    mutated_data = processor.apply(original_data, state)

The state dictionary is maintained across test cases to track incrementing
values and other stateful behavior.

Part of the Proprietary Protocol Fuzzer framework.
Last Updated: 2026-02-06
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import structlog

from core.engine.protocol_parser import ProtocolParser

logger = structlog.get_logger()


@dataclass
class BehaviorSpec:
    name: str
    operation: str
    block_index: int
    size: Optional[int]  # Size in BYTES for byte-aligned fields
    size_bits: Optional[int] = None  # Size in BITS for bit fields
    endian: str = "big"
    initial: int = 0
    step: int = 1
    wrap: Optional[int] = None
    value: int = 0  # for arithmetic
    is_bit_field: bool = False  # True if this is a sub-byte bit field


class BehaviorProcessor:
    """Applies declarative behaviors defined on data model blocks"""

    def __init__(self, data_model: Dict[str, Any]):
        self.data_model = data_model
        self.blocks = data_model.get("blocks", [])
        self.parser = ProtocolParser(data_model)
        self.specs: List[BehaviorSpec] = []
        self._build_plan()

    def _build_plan(self) -> None:
        for idx, block in enumerate(self.blocks):
            behavior = block.get("behavior")
            field_type = block.get("type", "")
            is_bit_field = field_type == "bits"
            size = self._block_size(block)
            size_bits = block.get("size") if is_bit_field else None

            if behavior:
                operation = behavior.get("operation") or behavior.get("type")
                if operation not in {"increment", "add_constant"}:
                    logger.warning(
                        "behavior_operation_unsupported",
                        block=block.get("name"),
                        operation=operation,
                    )
                else:
                    spec = BehaviorSpec(
                        name=block.get("name", "block"),
                        operation=operation,
                        block_index=idx,
                        size=size,
                        size_bits=size_bits,
                        endian=behavior.get("endian", block.get("endian", "big")),
                        initial=behavior.get("initial", 0),
                        step=behavior.get("step", 1),
                        wrap=behavior.get("wrap"),
                        value=behavior.get("value", 0),
                        is_bit_field=is_bit_field,
                    )
                    self.specs.append(spec)

    @staticmethod
    def _block_size(block: Dict[str, Any]) -> Optional[int]:
        """
        Get block size in BYTES for byte-aligned fields.
        Returns None for bit fields (use _block_size_bits instead).
        """
        field_type = block.get("type", "")
        if field_type == "bits":
            # Bit fields are handled separately - return None to signal
            # that bit-level tracking is needed
            return None
        if field_type in {"uint8", "int8", "byte"}:
            return 1
        if field_type in {"uint16", "int16"}:
            return 2
        if field_type in {"uint32", "int32"}:
            return 4
        if field_type in {"uint64", "int64"}:
            return 8
        if field_type == "bytes" and "size" in block:
            return block["size"]
        return None

    @staticmethod
    def _block_size_bits(block: Dict[str, Any]) -> Optional[int]:
        """
        Get block size in BITS for any field type.
        Returns the size in bits, accounting for both bit fields and byte-aligned fields.
        """
        field_type = block.get("type", "")
        if field_type == "bits":
            # Bit field - size is already in bits
            return block.get("size")
        if field_type in {"uint8", "int8", "byte"}:
            return 8
        if field_type in {"uint16", "int16"}:
            return 16
        if field_type in {"uint32", "int32"}:
            return 32
        if field_type in {"uint64", "int64"}:
            return 64
        if field_type == "bytes" and "size" in block:
            return block["size"] * 8
        return None

    def _resolved_block_size_bits(self, block: Dict[str, Any], value: Any) -> Optional[int]:
        """
        Get resolved block size in BITS, using parsed value for variable-length fields.
        """
        # Prefer explicit size in bits
        explicit = self._block_size_bits(block)
        if explicit is not None:
            return explicit

        field_type = block.get("type", "")
        if field_type == "bytes" and isinstance(value, (bytes, bytearray)):
            return len(value) * 8
        if field_type == "string" and isinstance(value, str):
            return len(value.encode(block.get("encoding", "utf-8"))) * 8

        return None

    def _resolved_block_size(self, block: Dict[str, Any], value: Any) -> Optional[int]:
        """
        Get resolved block size in BYTES for byte-aligned fields.
        Used by apply() to read/write field values from buffers.

        Note: Bit fields are NOT supported here as they require bit-level manipulation.
        """
        size_bits = self._resolved_block_size_bits(block, value)
        if size_bits is None:
            return None

        # For bit fields, return the packed byte size (rounded up)
        # However, behaviors on bit fields require special handling
        if block.get("type") == "bits":
            return (size_bits + 7) // 8

        # For byte-aligned fields, size should be a multiple of 8
        if size_bits % 8 != 0:
            return None

        return size_bits // 8

    def _compute_offset(self, target_index: int, parsed_fields: Dict[str, Any]) -> Optional[int]:
        """
        Compute byte offset to the target field, properly handling bit fields.

        Tracks position in bits internally, then converts to byte offset.
        Bit fields are packed together; byte-aligned fields force alignment.
        """
        bit_offset = 0

        for idx, block in enumerate(self.blocks[:target_index]):
            field_type = block.get("type", "")
            value = parsed_fields.get(block.get("name", ""))

            # For non-bit fields, ensure byte alignment first
            if field_type != "bits" and bit_offset % 8 != 0:
                bit_offset = ((bit_offset + 7) // 8) * 8

            size_bits = self._resolved_block_size_bits(block, value)
            if size_bits is None:
                logger.warning(
                    "behavior_offset_unknown",
                    field=block.get("name"),
                    target_index=target_index,
                )
                return None
            bit_offset += size_bits

        # Ensure byte alignment before returning (target field is byte-aligned)
        target_block = self.blocks[target_index] if target_index < len(self.blocks) else None
        if target_block and target_block.get("type") != "bits" and bit_offset % 8 != 0:
            bit_offset = ((bit_offset + 7) // 8) * 8

        return bit_offset // 8

    def has_behaviors(self) -> bool:
        return bool(self.specs)

    def initialize_state(self) -> Dict[str, int]:
        return {spec.name: spec.initial for spec in self.specs if spec.operation == "increment"}

    def apply(self, data: bytes, state: Dict[str, Any]) -> bytes:
        if not self.specs:
            return data

        try:
            parsed_fields = self.parser.parse(data)
        except Exception as exc:
            logger.warning("behavior_parse_failed", error=str(exc))
            return data

        buffer = bytearray(data)
        for spec in self.specs:
            block = self.blocks[spec.block_index]
            size = self._resolved_block_size(block, parsed_fields.get(block.get("name", "")))
            if size is None:
                logger.warning("behavior_unknown_size", field=spec.name)
                continue

            offset = self._compute_offset(spec.block_index, parsed_fields)
            if offset is None:
                continue

            start = offset
            end = offset + size
            if end > len(buffer):
                logger.warning(
                    "behavior_out_of_bounds",
                    field=spec.name,
                    needed=end,
                    available=len(buffer),
                )
                continue

            signed = block.get("type", "").startswith("int") and not block.get("type", "").startswith("uint")
            bits = size * 8
            modulus = 1 << bits
            wrap = spec.wrap or modulus

            if spec.operation == "increment":
                current = state.get(spec.name, spec.initial) % modulus
                next_value = (current + spec.step) % wrap
                store_value = next_value
                if signed and next_value >= (1 << (bits - 1)):
                    store_value = next_value - modulus
                buffer[start:end] = store_value.to_bytes(size, spec.endian, signed=signed)
                state[spec.name] = store_value
            elif spec.operation == "add_constant":
                raw = int.from_bytes(buffer[start:end], spec.endian, signed=signed)
                updated = (raw + spec.value) % wrap
                if signed and updated >= (1 << (bits - 1)):
                    updated = updated - modulus
                buffer[start:end] = updated.to_bytes(size, spec.endian, signed=signed)

        return bytes(buffer)


def build_behavior_processor(data_model: Dict[str, Any]) -> BehaviorProcessor:
    return BehaviorProcessor(data_model)
