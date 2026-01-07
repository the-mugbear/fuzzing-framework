"""Runtime helpers for protocol field behaviors"""
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
    size: Optional[int]
    endian: str = "big"
    initial: int = 0
    step: int = 1
    wrap: Optional[int] = None
    value: int = 0  # for arithmetic


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
            size = self._block_size(block)

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
                        endian=behavior.get("endian", block.get("endian", "big")),
                        initial=behavior.get("initial", 0),
                        step=behavior.get("step", 1),
                        wrap=behavior.get("wrap"),
                        value=behavior.get("value", 0),
                    )
                    self.specs.append(spec)

    @staticmethod
    def _block_size(block: Dict[str, Any]) -> Optional[int]:
        field_type = block.get("type", "")
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

    def _resolved_block_size(self, block: Dict[str, Any], value: Any) -> Optional[int]:
        # Prefer explicit size; otherwise use the actual parsed value length
        explicit = self._block_size(block)
        if explicit:
            return explicit

        if block.get("type") == "bytes" and isinstance(value, (bytes, bytearray)):
            return len(value)
        if block.get("type") == "string" and isinstance(value, str):
            return len(value.encode(block.get("encoding", "utf-8")))

        return None

    def _compute_offset(self, target_index: int, parsed_fields: Dict[str, Any]) -> Optional[int]:
        offset = 0
        for idx, block in enumerate(self.blocks[:target_index]):
            value = parsed_fields.get(block.get("name", ""))
            size = self._resolved_block_size(block, value)
            if size is None:
                logger.warning(
                    "behavior_offset_unknown",
                    field=block.get("name"),
                    target_index=target_index,
                )
                return None
            offset += size
        return offset

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
