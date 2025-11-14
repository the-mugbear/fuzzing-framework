"""Protocol development tools API endpoints."""
import binascii
from typing import Any, Dict

import structlog
from fastapi import APIRouter, HTTPException

from core.engine.protocol_parser import ProtocolParser
from core.engine.plugin_validator import validate_plugin_code
from core.models import ParseRequest, ParseResponse, ParsedFieldInfo, ValidationRequest, ValidationResult
from core.plugin_loader import PluginManager

logger = structlog.get_logger()
router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.post("/parse", response_model=ParseResponse)
async def parse_packet(request: ParseRequest) -> ParseResponse:
    """
    Parse a hex/base64 packet using protocol data_model.

    Returns parsed fields with offset and size information for UI highlighting.
    """
    try:
        # Load protocol plugin
        plugin_manager = PluginManager()
        try:
            plugin = plugin_manager.load_plugin(request.protocol)
        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"Protocol '{request.protocol}' not found: {str(e)}"
            )

        # Convert hex string to bytes
        hex_clean = request.hex_data.replace(" ", "").replace("\n", "").replace("\t", "")
        try:
            packet_bytes = bytes.fromhex(hex_clean)
        except ValueError as e:
            return ParseResponse(
                success=False,
                raw_hex="",
                total_bytes=0,
                error=f"Invalid hex string: {str(e)}"
            )

        # Parse the packet
        parser = ProtocolParser(plugin.data_model)

        try:
            fields_dict = parser.parse(packet_bytes)
        except Exception as e:
            return ParseResponse(
                success=False,
                raw_hex=packet_bytes.hex().upper(),
                total_bytes=len(packet_bytes),
                error=f"Parse failed: {str(e)}"
            )

        # Build field info with offsets
        parsed_fields = []
        offset = 0

        for block in plugin.data_model.get('blocks', []):
            field_name = block['name']
            field_type = block['type']
            field_value = fields_dict.get(field_name)

            # Calculate field size
            if field_type == 'bytes':
                if isinstance(field_value, bytes):
                    field_size = len(field_value)
                else:
                    field_size = block.get('size', 0)
            elif field_type in ['uint8', 'int8']:
                field_size = 1
            elif field_type in ['uint16', 'int16']:
                field_size = 2
            elif field_type in ['uint32', 'int32']:
                field_size = 4
            elif field_type in ['uint64', 'int64']:
                field_size = 8
            else:
                field_size = 0

            # Extract hex value for this field
            field_bytes = packet_bytes[offset:offset + field_size]
            hex_value = field_bytes.hex().upper()

            # Format value for display
            if isinstance(field_value, bytes):
                display_value = field_value.decode('utf-8', errors='replace')
            elif isinstance(field_value, int):
                display_value = f"0x{field_value:X} ({field_value})"
            else:
                display_value = str(field_value)

            parsed_fields.append(ParsedFieldInfo(
                name=field_name,
                value=display_value,
                type=field_type,
                offset=offset,
                size=field_size,
                mutable=block.get('mutable', True),
                description=block.get('description'),
                hex_value=hex_value
            ))

            offset += field_size

        return ParseResponse(
            success=True,
            fields=parsed_fields,
            raw_hex=packet_bytes.hex().upper(),
            total_bytes=len(packet_bytes),
            warnings=[]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("parse_packet_error", error=str(e), protocol=request.protocol)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.post("/validate-plugin", response_model=ValidationResult)
async def validate_plugin(request: ValidationRequest) -> ValidationResult:
    """
    Validate plugin Python source code.

    Performs syntax checking, validates data_model and state_model structure,
    and runs comprehensive validation checks.

    Returns validation issues categorized by severity (error/warning).
    """
    try:
        valid, issues, plugin_name = validate_plugin_code(request.plugin_code)

        # Count errors and warnings
        error_count = sum(1 for issue in issues if issue["severity"] == "error")
        warning_count = sum(1 for issue in issues if issue["severity"] == "warning")

        # Generate summary
        if valid:
            if warning_count > 0:
                summary = f"Plugin is valid with {warning_count} warning(s)"
            else:
                summary = "Plugin is valid with no issues"
        else:
            summary = f"Plugin has {error_count} error(s)"
            if warning_count > 0:
                summary += f" and {warning_count} warning(s)"

        return ValidationResult(
            valid=valid,
            plugin_name=plugin_name,
            issues=issues,
            summary=summary
        )

    except Exception as e:
        logger.error("validate_plugin_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")
