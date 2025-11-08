"""Runtime helpers for protocol field behaviors"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class BehaviorSpec:
    name: str
    operation: str
    offset: int
    size: int
    endian: str = "big"
    initial: int = 0
    step: int = 1
    wrap: Optional[int] = None
    value: int = 0  # for arithmetic


class BehaviorProcessor:
    """Applies declarative behaviors defined on data model blocks"""

    def __init__(self, data_model: Dict[str, Any]):
        self.specs: List[BehaviorSpec] = []
        self._build_plan(data_model)

    def _build_plan(self, data_model: Dict[str, Any]) -> None:
        offset = 0
        blocks = data_model.get("blocks", [])
        for block in blocks:
            block_type = block.get("type")
            behavior = block.get("behavior")
            size = self._block_size(block)
            if behavior and size is None:
                logger.warning(
                    "behavior_skipped_dynamic_block",
                    block=block.get("name"),
                )
                behavior = None

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
                        offset=offset,
                        size=size,
                        endian=behavior.get("endian", block.get("endian", "big")),
                        initial=behavior.get("initial", 0),
                        step=behavior.get("step", 1),
                        wrap=behavior.get("wrap"),
                        value=behavior.get("value", 0),
                    )
                    if spec.wrap is None:
                        spec.wrap = 1 << (spec.size * 8)
                    self.specs.append(spec)

            if size is None:
                # dynamic payload; cannot track offsets beyond this block reliably
                break
            offset += size

    @staticmethod
    def _block_size(block: Dict[str, Any]) -> Optional[int]:
        if block.get("type", "") in {"uint8", "byte"}:
            return 1
        if block.get("type") == "uint16":
            return 2
        if block.get("type") == "uint32":
            return 4
        if block.get("type") == "uint64":
            return 8
        if block.get("type") == "bytes" and "size" in block:
            return block["size"]
        return None

    def has_behaviors(self) -> bool:
        return bool(self.specs)

    def initialize_state(self) -> Dict[str, int]:
        return {spec.name: spec.initial for spec in self.specs if spec.operation == "increment"}

    def apply(self, data: bytes, state: Dict[str, Any]) -> bytes:
        if not self.specs:
            return data

        buffer = bytearray(data)
        for spec in self.specs:
            start = spec.offset
            end = spec.offset + spec.size
            if end > len(buffer):
                logger.warning(
                    "behavior_out_of_bounds",
                    field=spec.name,
                    needed=end,
                    available=len(buffer),
                )
                continue

            if spec.operation == "increment":
                current = state.get(spec.name, spec.initial)
                buffer[start:end] = current.to_bytes(spec.size, spec.endian, signed=False)
                next_value = current + spec.step
                if spec.wrap:
                    next_value %= spec.wrap
                state[spec.name] = next_value
            elif spec.operation == "add_constant":
                raw = int.from_bytes(buffer[start:end], spec.endian, signed=False)
                raw = (raw + spec.value) % (1 << (spec.size * 8))
                buffer[start:end] = raw.to_bytes(spec.size, spec.endian, signed=False)

        return bytes(buffer)


def build_behavior_processor(data_model: Dict[str, Any]) -> BehaviorProcessor:
    return BehaviorProcessor(data_model)
