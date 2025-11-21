"""One-off test execution endpoints."""
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.api.deps import get_orchestrator, get_plugin_manager
from core.engine.protocol_parser import ProtocolParser
from core.models import OneOffTestRequest, OneOffTestResult, ParsedFieldInfo
from core.plugin_loader import denormalize_data_model_from_json

logger = structlog.get_logger()
router = APIRouter(prefix="/api/tests", tags=["tests"])


class TestExecuteResponse(BaseModel):
    """Response format for mutation workbench test execution"""
    success: bool
    sent_bytes: int
    response_bytes: int
    response_hex: Optional[str] = None
    response_fields: Optional[list[ParsedFieldInfo]] = None
    duration_ms: float
    error: Optional[str] = None


@router.post("/execute", response_model=TestExecuteResponse)
async def execute_test(
    request: OneOffTestRequest,
    orchestrator=Depends(get_orchestrator),
    plugin_manager=Depends(get_plugin_manager),
):
    try:
        result = await orchestrator.execute_one_off(request)
        parsed_fields: list[ParsedFieldInfo] | None = None
        try:
            plugin = plugin_manager.load_plugin(request.protocol)
            if result.response and plugin.response_model:
                response_model = denormalize_data_model_from_json(plugin.response_model)
                parser = ProtocolParser(response_model)
                parsed_values = parser.parse(result.response)
                blocks = response_model.get("blocks", [])
                offset = 0
                parsed_fields = []
                for block in blocks:
                    field_name = block.get("name")
                    field_type = block.get("type", "")
                    size = 0
                    field_value = parsed_values.get(field_name)
                    if field_type == "bytes":
                        size = len(field_value) if isinstance(field_value, bytes) else block.get("size", 0)
                    elif field_type.startswith("uint") or field_type.startswith("int"):
                        size = int(field_type.replace("uint", "").replace("int", "") or 0) // 8
                    elif field_type == "string":
                        if isinstance(field_value, str):
                            size = len(field_value.encode(block.get("encoding", "utf-8")))
                    else:
                        if isinstance(field_value, bytes):
                            size = len(field_value)

                    chunk = result.response[offset:offset + size] if size else b""
                    value = parsed_values.get(field_name)
                    if isinstance(value, bytes):
                        try:
                            value = value.decode("utf-8")
                        except Exception:
                            value = value.hex()
                    parsed_fields.append(
                        ParsedFieldInfo(
                            name=field_name or "",
                            value=value,
                            hex_value=chunk.hex().upper(),
                            type=field_type,
                            offset=offset,
                            size=size,
                        )
                    )
                    offset += size
        except Exception as parsing_exc:  # pragma: no cover - best effort
            logger.debug("one_off_response_parse_failed", error=str(parsing_exc))

        # Transform OneOffTestResult to TestExecuteResponse format
        response_hex = None
        response_bytes = 0
        if result.response:
            response_hex = result.response.hex().upper()
            response_bytes = len(result.response)

        return TestExecuteResponse(
            success=result.success,
            sent_bytes=len(request.payload),
            response_bytes=response_bytes,
            response_hex=response_hex,
            response_fields=parsed_fields,
            duration_ms=result.execution_time_ms,
            error=None if result.success else str(result.result)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("one_off_execution_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to execute test")
