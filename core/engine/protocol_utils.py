"""
Protocol Analysis Utilities

Shared utilities for analyzing and working with protocol data models.
"""
from typing import Dict, Optional, Tuple
import structlog

logger = structlog.get_logger()


def find_command_field(data_model: Dict) -> Optional[str]:
    """
    Find the field that indicates message type/command in a protocol.

    Searches for fields with a 'values' dictionary, preferring
    fields named 'command' or 'message_type'.

    Args:
        data_model: Protocol data model dictionary

    Returns:
        Name of the command field, or None if not found
    """
    if not data_model:
        return None

    blocks = data_model.get("blocks", [])
    preferred_fields = ("command", "message_type")
    fallback_field = None

    for block in blocks:
        if "values" not in block:
            continue

        field_name = block.get("name")
        if field_name in preferred_fields:
            # Found preferred field name
            return field_name

        if fallback_field is None:
            # Store first field with values as fallback
            fallback_field = field_name

    return fallback_field


def build_message_type_mapping(data_model: Dict) -> Tuple[Optional[str], Dict[str, int]]:
    """
    Build mapping from message type names to command values.

    Args:
        data_model: Protocol data model dictionary

    Returns:
        Tuple of (command_field_name, mapping_dict) where mapping_dict maps
        message type names to their numeric command values.
        Returns (None, {}) if no command field found.

    Example:
        For a protocol with command field having values {0x01: "CONNECT", 0x02: "DATA"}:
        Returns ("command", {"CONNECT": 0x01, "DATA": 0x02})
    """
    if not data_model:
        return None, {}

    command_field = find_command_field(data_model)
    if not command_field:
        return None, {}

    # Find the block for this command field
    blocks = data_model.get("blocks", [])
    for block in blocks:
        if block.get("name") == command_field and "values" in block:
            mapping = {}
            values = block["values"]

            for cmd_value, cmd_name in values.items():
                # Handle JSON serialization converting int keys to strings
                if isinstance(cmd_value, str):
                    try:
                        cmd_value = int(cmd_value)
                    except ValueError:
                        logger.warning(
                            "invalid_command_value",
                            value=cmd_value,
                            name=cmd_name,
                            field=command_field
                        )
                        continue

                mapping[cmd_name] = cmd_value

            logger.debug(
                "message_type_mapping_built",
                command_field=command_field,
                num_types=len(mapping)
            )
            return command_field, mapping

    return None, {}


def build_message_type_map_with_field(
    data_model: Dict
) -> Dict[str, Tuple[str, int]]:
    """
    Build mapping from message type name to (field_name, value) tuple.

    This variant includes the field name in each mapping entry, useful for
    seed generation where you need to know both which field and which value.

    Args:
        data_model: Protocol data model dictionary

    Returns:
        Dict mapping message type name to (field_name, command_value) tuple

    Example:
        For a protocol with command field having values {0x01: "CONNECT", 0x02: "DATA"}:
        Returns {"CONNECT": ("command", 0x01), "DATA": ("command", 0x02)}
    """
    command_field, mapping = build_message_type_mapping(data_model)
    if not command_field:
        return {}

    # Convert to format including field name
    return {
        msg_type: (command_field, cmd_value)
        for msg_type, cmd_value in mapping.items()
    }
