"""
Protocol Parser - Bidirectional conversion between bytes and structured fields

Parses binary protocol messages into field dictionaries based on data_model,
and serializes them back with automatic length/checksum fixing.
"""
import struct
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


class ProtocolParser:
    """
    Parse and serialize protocol messages based on data_model specification.

    Supports:
    - Fixed and variable-length fields
    - Integer types (uint8/16/32/64, int8/16/32/64) with endianness
    - Byte arrays (fixed size or max_size)
    - Automatic length field updates (is_size_field)
    """

    def __init__(self, data_model: Dict[str, Any]):
        """
        Initialize parser with protocol data model.

        Args:
            data_model: Protocol definition with 'blocks' list
        """
        self.data_model = data_model
        self.blocks = data_model.get('blocks', [])

    def parse(self, data: bytes) -> Dict[str, Any]:
        """
        Parse binary data into field dictionary.

        Args:
            data: Raw protocol message bytes

        Returns:
            Dictionary mapping field names to values

        Raises:
            ValueError: If data cannot be parsed according to model
        """
        fields = {}
        offset = 0

        for block in self.blocks:
            field_name = block['name']
            field_type = block['type']

            try:
                if field_type == 'bytes':
                    # Byte array field
                    value, consumed = self._parse_bytes_field(data, offset, block, fields)
                elif field_type.startswith('uint') or field_type.startswith('int'):
                    # Integer field
                    value, consumed = self._parse_integer_field(data, offset, block)
                elif field_type == 'string':
                    # String field (treat as bytes then decode)
                    value, consumed = self._parse_string_field(data, offset, block, fields)
                else:
                    raise ValueError(f"Unsupported field type: {field_type}")

                fields[field_name] = value
                offset += consumed

            except Exception as e:
                logger.error(
                    "parse_field_error",
                    field=field_name,
                    offset=offset,
                    error=str(e)
                )
                raise ValueError(f"Failed to parse field '{field_name}': {e}")

        return fields

    def serialize(self, fields: Dict[str, Any]) -> bytes:
        """
        Serialize field dictionary to binary message.

        Automatically updates:
        - Length fields (is_size_field: True)
        - Checksums (if behavior defined)

        Args:
            fields: Dictionary mapping field names to values

        Returns:
            Binary protocol message
        """
        # First pass: auto-update dependent fields
        fields = self._auto_fix_fields(fields)

        # Second pass: serialize each field
        result = b''

        for block in self.blocks:
            field_name = block['name']
            field_type = block['type']
            value = fields.get(field_name)

            if value is None:
                # Use default if field not present
                value = block.get('default', self._get_default_value(field_type))

            try:
                if field_type == 'bytes':
                    result += self._serialize_bytes_field(value, block)
                elif field_type.startswith('uint') or field_type.startswith('int'):
                    result += self._serialize_integer_field(value, block)
                elif field_type == 'string':
                    result += self._serialize_string_field(value, block)
                else:
                    raise ValueError(f"Unsupported field type: {field_type}")

            except Exception as e:
                logger.error(
                    "serialize_field_error",
                    field=field_name,
                    value=value,
                    error=str(e)
                )
                raise ValueError(f"Failed to serialize field '{field_name}': {e}")

        return result

    def _parse_bytes_field(
        self,
        data: bytes,
        offset: int,
        block: dict,
        parsed_fields: dict
    ) -> tuple[bytes, int]:
        """Parse byte array field"""
        if 'size' in block:
            # Fixed size
            size = block['size']
            if offset + size > len(data):
                raise ValueError(f"Not enough data for fixed-size field (need {size}, have {len(data) - offset})")
            return data[offset:offset + size], size

        elif 'max_size' in block:
            # Variable size - read until end or max_size
            max_size = block['max_size']

            # Check if there's a length field that tells us the size
            length_field = self._find_length_field_for(block['name'])
            if length_field and length_field['name'] in parsed_fields:
                size = parsed_fields[length_field['name']]
                size = min(size, max_size)  # Respect max_size
                if offset + size > len(data):
                    size = len(data) - offset  # Read what's available
            else:
                # No length field - read remaining data up to max_size
                size = min(max_size, len(data) - offset)

            return data[offset:offset + size], size

        else:
            # No size specified - read all remaining
            return data[offset:], len(data) - offset

    def _parse_integer_field(
        self,
        data: bytes,
        offset: int,
        block: dict
    ) -> tuple[int, int]:
        """Parse integer field"""
        field_type = block['type']
        endian = block.get('endian', 'big')

        # Determine size and format
        type_info = self._get_integer_info(field_type, endian)
        size = type_info['size']
        fmt = type_info['format']

        if offset + size > len(data):
            raise ValueError(f"Not enough data for {field_type} (need {size}, have {len(data) - offset})")

        value = struct.unpack(fmt, data[offset:offset + size])[0]
        return value, size

    def _parse_string_field(
        self,
        data: bytes,
        offset: int,
        block: dict,
        parsed_fields: dict
    ) -> tuple[str, int]:
        """Parse string field"""
        # Parse as bytes first
        raw_bytes, consumed = self._parse_bytes_field(data, offset, block, parsed_fields)

        # Decode to string
        encoding = block.get('encoding', 'utf-8')
        try:
            value = raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            # Fallback to latin-1 which never fails
            value = raw_bytes.decode('latin-1')

        return value, consumed

    def _serialize_bytes_field(self, value: bytes, block: dict) -> bytes:
        """Serialize byte array field"""
        if not isinstance(value, bytes):
            value = bytes(value)

        if 'size' in block:
            # Fixed size - pad or truncate
            size = block['size']
            if len(value) < size:
                value = value + b'\x00' * (size - len(value))
            elif len(value) > size:
                value = value[:size]

        return value

    def _serialize_integer_field(self, value: int, block: dict) -> bytes:
        """Serialize integer field"""
        field_type = block['type']
        endian = block.get('endian', 'big')

        type_info = self._get_integer_info(field_type, endian)
        fmt = type_info['format']

        # Ensure value fits in type
        if field_type.startswith('uint'):
            max_val = (2 ** type_info['bits']) - 1
            value = value & max_val  # Wrap around

        return struct.pack(fmt, value)

    def _serialize_string_field(self, value: str, block: dict) -> bytes:
        """Serialize string field"""
        encoding = block.get('encoding', 'utf-8')
        value_bytes = value.encode(encoding)
        return self._serialize_bytes_field(value_bytes, block)

    def _auto_fix_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Automatically update dependent fields (lengths, checksums).

        Args:
            fields: Field dictionary

        Returns:
            Updated field dictionary
        """
        fields = fields.copy()

        # Update length fields
        for block in self.blocks:
            if block.get('is_size_field'):
                target_field = block.get('size_of')
                if target_field and target_field in fields:
                    # Calculate size of target field
                    target_value = fields[target_field]
                    if isinstance(target_value, bytes):
                        fields[block['name']] = len(target_value)
                    elif isinstance(target_value, str):
                        encoding = self._get_block(target_field).get('encoding', 'utf-8')
                        fields[block['name']] = len(target_value.encode(encoding))

        # TODO: Update checksum fields (when behavior system is integrated)

        return fields

    def _get_integer_info(self, field_type: str, endian: str) -> dict:
        """Get struct format and size for integer type"""
        endian_char = '>' if endian == 'big' else '<'

        type_map = {
            'uint8': {'format': 'B', 'size': 1, 'bits': 8},
            'uint16': {'format': f'{endian_char}H', 'size': 2, 'bits': 16},
            'uint32': {'format': f'{endian_char}I', 'size': 4, 'bits': 32},
            'uint64': {'format': f'{endian_char}Q', 'size': 8, 'bits': 64},
            'int8': {'format': 'b', 'size': 1, 'bits': 8},
            'int16': {'format': f'{endian_char}h', 'size': 2, 'bits': 16},
            'int32': {'format': f'{endian_char}i', 'size': 4, 'bits': 32},
            'int64': {'format': f'{endian_char}q', 'size': 8, 'bits': 64},
        }

        return type_map.get(field_type, {'format': 'B', 'size': 1, 'bits': 8})

    def _get_default_value(self, field_type: str) -> Any:
        """Get default value for field type"""
        if field_type.startswith('uint') or field_type.startswith('int'):
            return 0
        elif field_type == 'bytes':
            return b''
        elif field_type == 'string':
            return ''
        return None

    def _find_length_field_for(self, target_field: str) -> Optional[dict]:
        """Find the length field that specifies size of target_field"""
        for block in self.blocks:
            if block.get('is_size_field') and block.get('size_of') == target_field:
                return block
        return None

    def _get_block(self, field_name: str) -> dict:
        """Get block definition by field name"""
        for block in self.blocks:
            if block['name'] == field_name:
                return block
        return {}
