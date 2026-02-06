"""
Response planner - turns parsed responses into follow-up requests.

This module implements declarative response handling with support for
copying values from responses and applying transformations.

TRANSFORMATION SUPPORT:
=======================
When copying values from responses, you can apply transformations:

1. SIMPLE COPY:
   {"copy_from_response": "session_token"}

2. COPY WITH SINGLE OPERATION:
   {
       "copy_from_response": "server_value",
       "operation": "and_mask",
       "value": 0x1F
   }

3. COPY WITH BIT EXTRACTION:
   {
       "copy_from_response": "server_value",
       "extract_bits": {"start": 0, "count": 5}  # Extract 5 LSBs
   }

4. COPY WITH TRANSFORMATION PIPELINE:
   {
       "copy_from_response": "server_value",
       "transform": [
           {"operation": "and_mask", "value": 0x1F},  # Extract 5 LSBs
           {"operation": "invert", "bit_width": 5},   # Invert within 5 bits
       ]
   }

SUPPORTED OPERATIONS:
=====================
- add_constant: value + constant
- subtract_constant: value - constant
- xor_constant: value ^ constant
- and_mask: value & mask
- or_mask: value | mask
- shift_left: value << count
- shift_right: value >> count
- invert: ~value (bit_width RECOMMENDED to specify field size)
- modulo: value % divisor

For 'invert' operation:
- With bit_width (RECOMMENDED): Inverts only the specified number of bits
  Example: invert with bit_width=5 on value 0x0A (01010) -> 0x15 (10101)
- Without bit_width: Infers width from value (8/16/32 bits) - may be incorrect!
  A warning is logged to help identify missing bit_width parameters.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Union

import structlog

from core.engine.protocol_parser import ProtocolParser

logger = structlog.get_logger()


class ResponsePlanner:
    """
    Evaluates parsed responses and builds follow-up messages.

    Plugins describe response handlers in a declarative format:

    response_handlers = [
        {
            "name": "sync_session_id",
            "match": {"command": 0x02},
            "set_fields": {
                "command": 0x10,
                "session_id": {"copy_from_response": "session_token"},
            },
        }
    ]

    Advanced example with bit manipulation:

    response_handlers = [
        {
            "name": "derive_header_from_token",
            "match": {"status": 0x00},
            "set_fields": {
                # Copy server value directly
                "session_token": {"copy_from_response": "server_token"},

                # Extract 5 LSBs and invert them for header field
                "header_check": {
                    "copy_from_response": "server_token",
                    "transform": [
                        {"operation": "and_mask", "value": 0x1F},
                        {"operation": "invert", "bit_width": 5},
                    ]
                },
            },
        }
    ]
    """

    def __init__(
        self,
        request_model: Dict[str, Any],
        response_model: Optional[Dict[str, Any]] = None,
        handlers: Optional[List[Dict[str, Any]]] = None,
    ):
        self.request_parser = ProtocolParser(request_model)
        # Use response model if provided; otherwise requests and responses share layout.
        parser_model = response_model or request_model
        self.response_parser = ProtocolParser(parser_model)
        self.handlers = handlers or []
        self.default_fields = self.request_parser.build_default_fields()

        # Track handlers that have fired (for once_per_reset support)
        # Handlers with "once_per_reset": true will only fire once until reset() is called
        self._fired_handlers: set[str] = set()

    def reset(self) -> None:
        """
        Reset handler activation tracking.

        Call this when the protocol state machine resets to allow
        handlers with 'once_per_reset: true' to fire again.
        """
        self._fired_handlers.clear()
        logger.debug("response_planner_reset", cleared_handlers=len(self._fired_handlers))

    def plan(self, response_bytes: Optional[bytes]) -> List[Dict[str, Any]]:
        """
        Plan follow-up requests based on a raw response.

        Handlers with 'once_per_reset: true' will only fire once until
        reset() is called. This prevents infinite followup loops.
        """
        if not response_bytes:
            return []

        try:
            parsed_response = self.response_parser.parse(response_bytes)
        except Exception as exc:
            logger.debug("response_parse_failed", error=str(exc))
            return []

        followups: List[Dict[str, Any]] = []

        for handler in self.handlers:
            handler_name = handler.get("name", "response_handler")

            # Check if handler has already fired (once_per_reset support)
            if handler.get("once_per_reset", False):
                if handler_name in self._fired_handlers:
                    logger.debug(
                        "handler_skipped_already_fired",
                        handler=handler_name,
                    )
                    continue

            if not self._matches(handler.get("match", {}), parsed_response):
                continue

            payload = self._build_payload(handler, parsed_response)
            if payload is None:
                continue

            # Mark handler as fired if once_per_reset is enabled
            if handler.get("once_per_reset", False):
                self._fired_handlers.add(handler_name)
                logger.debug(
                    "handler_marked_fired",
                    handler=handler_name,
                )

            followups.append(
                {
                    "payload": payload,
                    "handler": handler_name,
                    "context": {
                        "parsed_response": parsed_response,
                        "match": handler.get("match", {}),
                    },
                }
            )

        return followups

    def extract_overrides(
        self, parsed_response: Dict[str, Any]
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Public helper to compute field overrides from response handlers.

        Returns:
            Tuple of (overrides dict, matched handler definitions)
        """
        updates: Dict[str, Any] = {}
        matched: List[Dict[str, Any]] = []

        for handler in self.handlers:
            if not self._matches(handler.get("match", {}), parsed_response):
                continue

            matched.append(handler)
            for field_name, spec in (handler.get("set_fields") or {}).items():
                value = self._resolve_field_value(spec, parsed_response)
                if value is not None:
                    updates[field_name] = value

        return updates, matched

    def _matches(self, match: Dict[str, Any], parsed_response: Dict[str, Any]) -> bool:
        if not match:
            return True
        for field, expected in match.items():
            value = parsed_response.get(field)
            if isinstance(expected, list):
                if value not in expected:
                    return False
            else:
                if value != expected:
                    return False
        return True

    def _build_payload(self, handler: Dict[str, Any], parsed_response: Dict[str, Any]) -> Optional[bytes]:
        set_fields = (
            handler.get("set_fields")
            or handler.get("next_fields")
            or handler.get("next_message")
            or {}
        )
        if not isinstance(set_fields, dict):
            logger.debug("response_handler_invalid_fields", handler=handler.get("name"))
            return None

        fields = deepcopy(self.default_fields)
        for field_name, spec in set_fields.items():
            fields[field_name] = self._resolve_field_value(spec, parsed_response)

        try:
            return self.request_parser.serialize(fields)
        except Exception as exc:
            logger.warning(
                "response_followup_serialize_failed",
                handler=handler.get("name"),
                error=str(exc),
            )
            return None

    @staticmethod
    def _resolve_field_value(spec: Any, parsed_response: Dict[str, Any]) -> Any:
        """
        Resolve a field value specification to an actual value.

        Supports:
        - Literal values (int, str, bytes, etc.)
        - {"copy_from_response": "field_name"} - copy from response
        - {"literal": value} - explicit literal wrapper
        - {"copy_from_response": ..., "extract_bits": {...}} - bit extraction
        - {"copy_from_response": ..., "operation": ..., "value": ...} - single op
        - {"copy_from_response": ..., "transform": [...]} - operation pipeline
        """
        if isinstance(spec, dict):
            if "copy_from_response" in spec:
                value = parsed_response.get(spec["copy_from_response"])

                # Bit extraction support for sub-byte field manipulation
                # Format: {"start": 4, "count": 4} extracts 4 bits starting at bit 4
                if "extract_bits" in spec:
                    start_bit = spec["extract_bits"].get("start", 0)
                    num_bits = spec["extract_bits"].get("count", 8)

                    if isinstance(value, int):
                        mask = (1 << num_bits) - 1
                        value = (value >> start_bit) & mask

                # Support for transformation pipeline (list of operations)
                # Each transform is: {"operation": "op_name", "value": x, "bit_width": y}
                if "transform" in spec:
                    transforms = spec["transform"]
                    if isinstance(transforms, list):
                        for transform in transforms:
                            if isinstance(transform, dict):
                                value = ResponsePlanner._apply_operation(
                                    value,
                                    transform.get("operation"),
                                    transform.get("value"),
                                    transform.get("bit_width"),
                                )

                # Support for single operation (backward compatible)
                elif "operation" in spec:
                    value = ResponsePlanner._apply_operation(
                        value,
                        spec.get("operation"),
                        spec.get("value"),
                        spec.get("bit_width"),
                    )

                return value
            if "literal" in spec:
                return spec["literal"]
        return spec

    @staticmethod
    def _apply_operation(
        value: Any,
        operation: Optional[str],
        op_value: Any = None,
        bit_width: Optional[int] = None,
    ) -> Any:
        """
        Apply a single transformation operation to a value.

        Args:
            value: The input value (must be int for most operations)
            operation: Operation name (add_constant, invert, and_mask, etc.)
            op_value: Operation parameter (constant to add, mask value, etc.)
            bit_width: For invert operation, limits inversion to N bits

        Returns:
            Transformed value

        Supported operations:
            - add_constant: value + op_value
            - subtract_constant: value - op_value
            - xor_constant: value ^ op_value
            - and_mask: value & op_value
            - or_mask: value | op_value
            - shift_left: value << op_value
            - shift_right: value >> op_value
            - invert: bitwise NOT, optionally limited to bit_width bits
            - modulo: value % op_value
        """
        if not isinstance(value, int):
            return value

        if operation is None:
            return value

        # Parse op_value if it's a string (allows hex like "0x1F")
        if isinstance(op_value, str):
            try:
                op_value = int(op_value, 0)
            except ValueError:
                op_value = None

        # Operations that require op_value
        if operation == "add_constant":
            if op_value is None:
                return value
            return value + op_value

        if operation == "subtract_constant":
            if op_value is None:
                return value
            return value - op_value

        if operation == "xor_constant":
            if op_value is None:
                return value
            return value ^ op_value

        if operation == "and_mask":
            if op_value is None:
                return value
            return value & op_value

        if operation == "or_mask":
            if op_value is None:
                return value
            return value | op_value

        if operation == "shift_left":
            if op_value is None:
                return value
            return value << op_value

        if operation == "shift_right":
            if op_value is None:
                return value
            return value >> op_value

        if operation == "modulo":
            if op_value is None or op_value == 0:
                return value
            return value % op_value

        # Invert operation - bitwise NOT with optional bit width limit
        if operation == "invert":
            if bit_width is not None and bit_width > 0:
                # Invert only within the specified bit width
                # Example: invert 5 bits -> XOR with 0x1F (0b11111)
                mask = (1 << bit_width) - 1
                return (~value) & mask
            else:
                # No bit_width specified - this is likely a bug in the plugin
                # Log a warning to help users identify the issue
                logger.warning(
                    "invert_missing_bit_width",
                    message="invert operation without bit_width may produce incorrect results",
                    value=value,
                    hint="Add 'bit_width' parameter to specify field size (e.g., 8 for uint8)",
                )
                # Use op_value as explicit mask if provided
                if op_value is not None:
                    return (~value) & op_value
                # Infer minimum bit width from value to avoid excessive bits
                # This uses the smallest standard field size that fits the value
                if value <= 0xFF:
                    inferred_width = 8
                elif value <= 0xFFFF:
                    inferred_width = 16
                else:
                    inferred_width = 32
                mask = (1 << inferred_width) - 1
                return (~value) & mask

        # Unknown operation - return unchanged
        logger.warning("unknown_transform_operation", operation=operation)
        return value
