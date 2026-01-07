"""
Response planner - turns parsed responses into follow-up requests.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

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

    def plan(self, response_bytes: Optional[bytes]) -> List[Dict[str, Any]]:
        """Plan follow-up requests based on a raw response."""
        if not response_bytes:
            return []

        try:
            parsed_response = self.response_parser.parse(response_bytes)
        except Exception as exc:
            logger.debug("response_parse_failed", error=str(exc))
            return []

        followups: List[Dict[str, Any]] = []

        for handler in self.handlers:
            if not self._matches(handler.get("match", {}), parsed_response):
                continue

            payload = self._build_payload(handler, parsed_response)
            if payload is None:
                continue

            followups.append(
                {
                    "payload": payload,
                    "handler": handler.get("name", "response_handler"),
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
        if isinstance(spec, dict):
            if "copy_from_response" in spec:
                return parsed_response.get(spec["copy_from_response"])
            if "literal" in spec:
                return spec["literal"]
        return spec
