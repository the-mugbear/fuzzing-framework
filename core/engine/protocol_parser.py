"""
Protocol Parser - Bidirectional conversion between bytes and structured fields

Parses binary protocol messages into field dictionaries based on data_model,
and serializes them back with automatic length/checksum fixing.
"""
import struct
import zlib
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
        bit_offset = 0  # Track position in bits

        for block in self.blocks:
            field_name = block['name']
            field_type = block['type']

            try:
                if field_type == 'bits':
                    # Sub-byte bit field
                    value, bits_consumed = self._parse_bits_field(data, bit_offset, block)
                    fields[field_name] = value
                    bit_offset += bits_consumed

                elif field_type == 'bytes':
                    # Byte array field - ensure byte alignment
                    if bit_offset % 8 != 0:
                        bit_offset = ((bit_offset + 7) // 8) * 8  # Pad to next byte
                    byte_offset = bit_offset // 8
                    value, bytes_consumed = self._parse_bytes_field(data, byte_offset, block, fields)
                    fields[field_name] = value
                    bit_offset += bytes_consumed * 8

                elif field_type.startswith('uint') or field_type.startswith('int'):
                    # Integer field - ensure byte alignment
                    if bit_offset % 8 != 0:
                        bit_offset = ((bit_offset + 7) // 8) * 8  # Pad to next byte
                    byte_offset = bit_offset // 8
                    value, bytes_consumed = self._parse_integer_field(data, byte_offset, block)
                    fields[field_name] = value
                    bit_offset += bytes_consumed * 8

                elif field_type == 'string':
                    # String field - ensure byte alignment
                    if bit_offset % 8 != 0:
                        bit_offset = ((bit_offset + 7) // 8) * 8  # Pad to next byte
                    byte_offset = bit_offset // 8
                    value, bytes_consumed = self._parse_string_field(data, byte_offset, block, fields)
                    fields[field_name] = value
                    bit_offset += bytes_consumed * 8

                else:
                    raise ValueError(f"Unsupported field type: {field_type}")

            except Exception as e:
                logger.error(
                    "parse_field_error",
                    field=field_name,
                    bit_offset=bit_offset,
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
        # Check if protocol has checksum fields
        has_checksums = any(
            block.get('is_checksum') or block.get('checksum_algorithm')
            for block in self.blocks
        )

        # If checksums are present, use two-pass serialization
        if has_checksums:
            return self.serialize_with_checksums(fields)

        # Otherwise, use simple single-pass serialization
        # First pass: auto-update dependent fields
        fields = self._auto_fix_fields(fields)

        # Second pass: serialize each field with bit-level tracking
        result = bytearray()
        bit_offset = 0
        bit_buffer = 0  # Accumulator for partial bytes

        for block in self.blocks:
            field_name = block['name']
            field_type = block['type']
            value = fields.get(field_name)

            if value is None:
                # Use default if field not present
                value = block.get('default', self._get_default_value(field_type))

            try:
                if field_type == 'bits':
                    # Serialize bit field
                    partial_bytes, bits_produced = self._serialize_bits_field(value, block, bit_offset)

                    # Merge partial bytes with buffer
                    bit_in_byte = bit_offset % 8
                    for i, byte_val in enumerate(partial_bytes):
                        if bit_in_byte == 0 and i == 0:
                            # First byte is complete, emit directly
                            result.append(byte_val)
                        else:
                            # Combine with bit_buffer
                            bit_buffer |= byte_val
                            if bit_in_byte + 8 >= 8 or i < len(partial_bytes) - 1:
                                result.append(bit_buffer)
                                bit_buffer = 0

                    bit_offset += bits_produced

                elif field_type == 'bytes':
                    # Byte field - ensure byte alignment
                    if bit_offset % 8 != 0:
                        # Flush partial byte
                        result.append(bit_buffer)
                        bit_buffer = 0
                        bit_offset = ((bit_offset + 7) // 8) * 8
                    result.extend(self._serialize_bytes_field(value, block))
                    bit_offset += len(self._serialize_bytes_field(value, block)) * 8

                elif field_type.startswith('uint') or field_type.startswith('int'):
                    # Integer field - ensure byte alignment
                    if bit_offset % 8 != 0:
                        # Flush partial byte
                        result.append(bit_buffer)
                        bit_buffer = 0
                        bit_offset = ((bit_offset + 7) // 8) * 8
                    serialized = self._serialize_integer_field(value, block)
                    result.extend(serialized)
                    bit_offset += len(serialized) * 8

                elif field_type == 'string':
                    # String field - ensure byte alignment
                    if bit_offset % 8 != 0:
                        # Flush partial byte
                        result.append(bit_buffer)
                        bit_buffer = 0
                        bit_offset = ((bit_offset + 7) // 8) * 8
                    serialized = self._serialize_string_field(value, block)
                    result.extend(serialized)
                    bit_offset += len(serialized) * 8

                else:
                    raise ValueError(f"Unsupported field type: {field_type}")

            except Exception as e:
                logger.error(
                    "serialize_field_error",
                    field=field_name,
                    value=value,
                    bit_offset=bit_offset,
                    error=str(e)
                )
                raise ValueError(f"Failed to serialize field '{field_name}': {e}")

        # Flush remaining partial byte if any
        if bit_offset % 8 != 0:
            result.append(bit_buffer)

        return bytes(result)

    def _serialize_without_checksum(self, fields: Dict[str, Any]) -> bytes:
        """
        Internal method to serialize without checksum processing.
        This avoids infinite recursion when serialize_with_checksums calls it.
        """
        # Auto-update dependent fields (lengths, but NOT checksums)
        fields = self._auto_fix_fields(fields)

        # Serialize each field with bit-level tracking
        result = bytearray()
        bit_offset = 0
        bit_buffer = 0  # Accumulator for partial bytes

        for block in self.blocks:
            field_name = block['name']
            field_type = block['type']
            value = fields.get(field_name)

            if value is None:
                # Use default if field not present
                value = block.get('default', self._get_default_value(field_type))

            try:
                if field_type == 'bits':
                    # Serialize bit field
                    partial_bytes, bits_produced = self._serialize_bits_field(value, block, bit_offset)

                    # Merge partial bytes with buffer
                    bit_in_byte = bit_offset % 8
                    for i, byte_val in enumerate(partial_bytes):
                        if bit_in_byte == 0 and i == 0:
                            # First byte is complete, emit directly
                            result.append(byte_val)
                        else:
                            # Combine with bit_buffer
                            bit_buffer |= byte_val
                            if bit_in_byte + 8 >= 8 or i < len(partial_bytes) - 1:
                                result.append(bit_buffer)
                                bit_buffer = 0

                    bit_offset += bits_produced

                elif field_type == 'bytes':
                    # Byte field - ensure byte alignment
                    if bit_offset % 8 != 0:
                        # Flush partial byte
                        result.append(bit_buffer)
                        bit_buffer = 0
                        bit_offset = ((bit_offset + 7) // 8) * 8
                    result.extend(self._serialize_bytes_field(value, block))
                    bit_offset += len(self._serialize_bytes_field(value, block)) * 8

                elif field_type.startswith('uint') or field_type.startswith('int'):
                    # Integer field - ensure byte alignment
                    if bit_offset % 8 != 0:
                        # Flush partial byte
                        result.append(bit_buffer)
                        bit_buffer = 0
                        bit_offset = ((bit_offset + 7) // 8) * 8
                    serialized = self._serialize_integer_field(value, block)
                    result.extend(serialized)
                    bit_offset += len(serialized) * 8

                elif field_type == 'string':
                    # String field - ensure byte alignment
                    if bit_offset % 8 != 0:
                        # Flush partial byte
                        result.append(bit_buffer)
                        bit_buffer = 0
                        bit_offset = ((bit_offset + 7) // 8) * 8
                    serialized = self._serialize_string_field(value, block)
                    result.extend(serialized)
                    bit_offset += len(serialized) * 8

                else:
                    raise ValueError(f"Unsupported field type: {field_type}")

            except Exception as e:
                logger.error(
                    "serialize_field_error",
                    field=field_name,
                    value=value,
                    bit_offset=bit_offset,
                    error=str(e)
                )
                raise ValueError(f"Failed to serialize field '{field_name}': {e}")

        # Flush remaining partial byte if any
        if bit_offset % 8 != 0:
            result.append(bit_buffer)

        return bytes(result)

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

    def _parse_bits_field(
        self,
        data: bytes,
        bit_offset: int,
        block: dict
    ) -> tuple[int, int]:
        """
        Parse arbitrary-width bit field.

        Args:
            data: Raw bytes to parse from
            bit_offset: Starting bit position (0 = MSB of byte 0)
            block: Field definition with 'size', 'bit_order', and optional 'endian'

        Returns:
            (value, bits_consumed)
        """
        num_bits = block['size']
        bit_order = block.get('bit_order', 'msb')  # Default MSB-first within byte
        endian = block.get('endian', 'big')  # Default big-endian for multi-byte fields

        # Calculate byte range
        byte_offset = bit_offset // 8
        bit_in_byte = bit_offset % 8
        bytes_needed = (bit_in_byte + num_bits + 7) // 8

        if byte_offset + bytes_needed > len(data):
            raise ValueError(f"Not enough data for {num_bits}-bit field")

        # Extract bytes into integer
        value = 0

        # Handle endianness for multi-byte bit fields
        if bytes_needed > 1 and endian == 'little':
            # Little-endian: Read bytes in reverse order
            for i in range(bytes_needed - 1, -1, -1):
                value = (value << 8) | data[byte_offset + i]
        else:
            # Big-endian (default): Read bytes MSB-first
            for i in range(bytes_needed):
                value = (value << 8) | data[byte_offset + i]

        # Shift to align field based on bit_order
        if bit_order == 'msb':
            # MSB-first: shift right to extract upper bits
            shift = (bytes_needed * 8) - bit_in_byte - num_bits
            mask = (1 << num_bits) - 1
            value = (value >> shift) & mask
        else:  # lsb
            # LSB-first: extract from lower bits
            shift = bit_in_byte
            mask = (1 << num_bits) - 1
            value = (value >> shift) & mask

        return value, num_bits

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

    def _serialize_bits_field(self, value: int, block: dict, bit_offset: int) -> tuple[bytes, int]:
        """
        Serialize arbitrary-width bit field.

        Returns:
            (partial_bytes, bits_produced)

        Note: May return partial byte that needs combining with next field
        """
        num_bits = block['size']
        bit_order = block.get('bit_order', 'msb')
        endian = block.get('endian', 'big')

        # Mask value to bit width
        mask = (1 << num_bits) - 1
        value = value & mask

        # Calculate byte span
        byte_offset = bit_offset // 8
        bit_in_byte = bit_offset % 8
        bytes_needed = (bit_in_byte + num_bits + 7) // 8

        # Pack bits into bytes based on bit_order
        if bit_order == 'msb':
            # MSB-first: shift left to position in upper bits
            shift = (bytes_needed * 8) - bit_in_byte - num_bits
            packed = value << shift
        else:  # lsb
            # LSB-first: position in lower bits
            shift = bit_in_byte
            packed = value << shift

        # Convert to bytes with endianness handling
        result = []
        if bytes_needed > 1 and endian == 'little':
            # Little-endian: Emit bytes in reverse order
            for i in range(bytes_needed):
                byte_val = (packed >> (i * 8)) & 0xFF
                result.append(byte_val)
        else:
            # Big-endian (default): Emit bytes MSB-first
            for i in range(bytes_needed):
                byte_val = (packed >> ((bytes_needed - 1 - i) * 8)) & 0xFF
                result.append(byte_val)

        return bytes(result), num_bits

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

        # Update length fields (size fields)
        for block in self.blocks:
            if not block.get('is_size_field'):
                continue

            targets = self._normalize_size_of_targets(block.get('size_of'))
            if not targets:
                continue

            # Calculate total length in BITS
            total_length_bits = 0
            for target_field in targets:
                target_block = self._get_block(target_field)
                if not target_block:
                    continue

                target_value = fields.get(target_field)
                if target_value is None:
                    if 'default' in target_block:
                        target_value = target_block['default']
                    else:
                        target_value = self._get_default_value(target_block.get('type', ''))

                # _calculate_field_length now returns bits
                total_length_bits += self._calculate_field_length(target_block, target_value)

            # Convert to size field's unit
            size_unit = block.get('size_unit', 'bytes')  # Default: bytes for backward compatibility
            if size_unit == 'bits':
                fields[block['name']] = total_length_bits
            elif size_unit == 'bytes':
                fields[block['name']] = (total_length_bits + 7) // 8  # Round up to whole bytes
            elif size_unit == 'words':  # 32-bit words
                fields[block['name']] = (total_length_bits + 31) // 32
            elif size_unit == 'dwords':  # 16-bit words (double-byte words)
                fields[block['name']] = (total_length_bits + 15) // 16
            else:
                # Unknown unit, default to bytes
                logger.warning(
                    "unknown_size_unit",
                    field=block['name'],
                    size_unit=size_unit,
                    defaulting_to="bytes"
                )
                fields[block['name']] = (total_length_bits + 7) // 8

        # Update checksum fields
        # Note: Checksums must be calculated AFTER serialization, so we'll do a two-pass approach
        # For now, we'll set checksums to placeholder values and they'll be fixed in a post-processing step

        return fields

    def serialize_with_checksums(self, fields: Dict[str, Any]) -> bytes:
        """
        Serialize fields and automatically compute checksums.

        This is a two-pass serialization:
        1. Serialize with placeholder checksum values
        2. Calculate actual checksums over the serialized data
        3. Update checksum fields in place

        Args:
            fields: Field dictionary

        Returns:
            Binary message with correct checksums
        """
        # First pass: serialize with auto-fixed fields (lengths) but WITHOUT checksums
        result = self._serialize_without_checksum(fields)

        # Find checksum fields and their positions (tracking in bits)
        checksum_fields = []
        bit_offset = 0
        for block in self.blocks:
            field_type = block.get('type', '')

            if block.get('is_checksum') or block.get('checksum_algorithm'):
                # Checksum fields should be byte-aligned
                if bit_offset % 8 != 0:
                    logger.warning(
                        "checksum_field_not_byte_aligned",
                        field=block['name'],
                        bit_offset=bit_offset
                    )
                    bit_offset = ((bit_offset + 7) // 8) * 8  # Align to byte

                checksum_fields.append({
                    'block': block,
                    'offset': bit_offset // 8,  # Convert to byte offset
                })

            # Calculate field size to track offset
            if field_type == 'bits':
                bit_offset += block.get('size', 0)
            elif field_type.startswith('uint') or field_type.startswith('int'):
                # Ensure byte alignment
                if bit_offset % 8 != 0:
                    bit_offset = ((bit_offset + 7) // 8) * 8
                bit_offset += self._get_integer_info(field_type, block.get('endian', 'big'))['size'] * 8
            else:
                # bytes, string - ensure byte alignment
                if bit_offset % 8 != 0:
                    bit_offset = ((bit_offset + 7) // 8) * 8
                field_size = self._get_field_size(block, fields.get(block['name']))
                bit_offset += field_size * 8

        # If no checksum fields, return as-is
        if not checksum_fields:
            return result

        # Second pass: calculate and update checksums
        result_bytes = bytearray(result)
        for checksum_info in checksum_fields:
            block = checksum_info['block']
            checksum_offset = checksum_info['offset']

            # Determine what data to checksum
            checksum_data = self._get_checksum_data(
                result_bytes,
                block,
                checksum_offset
            )

            # Calculate checksum
            algorithm = block.get('checksum_algorithm', 'crc32')
            checksum_value = self._calculate_checksum(checksum_data, algorithm)

            # Update checksum in result
            field_type = block['type']
            endian = block.get('endian', 'big')
            type_info = self._get_integer_info(field_type, endian)
            checksum_bytes = struct.pack(type_info['format'], checksum_value)

            # Replace checksum bytes in result
            checksum_size = type_info['size']
            result_bytes[checksum_offset:checksum_offset + checksum_size] = checksum_bytes

            logger.debug(
                "checksum_calculated",
                field=block['name'],
                algorithm=algorithm,
                value=hex(checksum_value),
                offset=checksum_offset
            )

        return bytes(result_bytes)

    def _get_field_size(self, block: dict, value: Any) -> int:
        """
        Get the serialized size of a field in BYTES.

        Note: For bit fields, this returns the size rounded up to whole bytes.
        """
        field_type = block.get('type', '')

        if field_type == 'bits':
            # Bit field - return size in bytes (rounded up)
            num_bits = block.get('size', 0)
            return (num_bits + 7) // 8

        if 'size' in block:
            return block['size']

        if field_type.startswith('uint') or field_type.startswith('int'):
            return self._get_integer_info(field_type, block.get('endian', 'big'))['size']

        # For variable-length fields, estimate from value
        return self._calculate_field_length(block, value)

    def _get_checksum_data(
        self,
        data: bytes,
        checksum_block: dict,
        checksum_offset: int
    ) -> bytes:
        """
        Extract the portion of data that should be checksummed.

        Args:
            data: Full serialized message
            checksum_block: Block definition for checksum field
            checksum_offset: Offset of checksum field in message

        Returns:
            Bytes to checksum
        """
        checksum_over = checksum_block.get('checksum_over')

        if not checksum_over:
            # Default: checksum everything except the checksum field itself
            checksum_size = self._get_field_size(checksum_block, None)
            return data[:checksum_offset] + data[checksum_offset + checksum_size:]

        if checksum_over == 'all':
            # Checksum entire message except checksum field
            checksum_size = self._get_field_size(checksum_block, None)
            return data[:checksum_offset] + data[checksum_offset + checksum_size:]

        if checksum_over == 'before':
            # Checksum everything before the checksum field
            return data[:checksum_offset]

        if checksum_over == 'after':
            # Checksum everything after the checksum field
            checksum_size = self._get_field_size(checksum_block, None)
            return data[checksum_offset + checksum_size:]

        if isinstance(checksum_over, list):
            # Checksum specific fields (concatenate their values)
            # This requires knowing field positions, which is complex
            # For now, fall back to 'all'
            logger.warning(
                "checksum_over_list_not_implemented",
                field=checksum_block['name'],
                falling_back_to_all=True
            )
            checksum_size = self._get_field_size(checksum_block, None)
            return data[:checksum_offset] + data[checksum_offset + checksum_size:]

        # Unknown checksum_over value
        checksum_size = self._get_field_size(checksum_block, None)
        return data[:checksum_offset] + data[checksum_offset + checksum_size:]

    def _calculate_checksum(self, data: bytes, algorithm: str) -> int:
        """
        Calculate checksum using specified algorithm.

        Args:
            data: Data to checksum
            algorithm: Algorithm name (crc32, sum, xor, adler32)

        Returns:
            Checksum value as integer
        """
        algorithm = algorithm.lower()

        if algorithm == 'crc32':
            # CRC32 (used in PNG, ZIP, etc.)
            return zlib.crc32(data) & 0xFFFFFFFF

        elif algorithm == 'adler32':
            # Adler32 (faster than CRC32, used in zlib)
            return zlib.adler32(data) & 0xFFFFFFFF

        elif algorithm == 'sum':
            # Simple sum of all bytes (modulo 256 or larger)
            return sum(data) & 0xFFFFFFFF

        elif algorithm == 'xor':
            # XOR of all bytes
            result = 0
            for byte in data:
                result ^= byte
            return result

        elif algorithm == 'sum8':
            # 8-bit sum
            return sum(data) & 0xFF

        elif algorithm == 'sum16':
            # 16-bit sum
            return sum(data) & 0xFFFF

        else:
            logger.warning(
                "unknown_checksum_algorithm",
                algorithm=algorithm,
                using_default='crc32'
            )
            return zlib.crc32(data) & 0xFFFFFFFF

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
        if field_type == 'bits':
            return 0
        elif field_type.startswith('uint') or field_type.startswith('int'):
            return 0
        elif field_type == 'bytes':
            return b''
        elif field_type == 'string':
            return ''
        return None

    def build_default_fields(self) -> Dict[str, Any]:
        """Build a base field dictionary using block defaults."""
        defaults: Dict[str, Any] = {}
        for block in self.blocks:
            field_name = block.get('name')
            if not field_name:
                continue
            default = block.get('default')
            if default is None:
                default = self._get_default_value(block.get('type', ''))
            defaults[field_name] = self._clone_default(default)
        return defaults

    def _find_length_field_for(self, target_field: str) -> Optional[dict]:
        """Find the length field that specifies size of target_field"""
        for block in self.blocks:
            if not block.get('is_size_field'):
                continue

            targets = self._normalize_size_of_targets(block.get('size_of'))
            if len(targets) == 1 and targets[0] == target_field:
                return block
        return None

    def _get_block(self, field_name: str) -> dict:
        """Get block definition by field name"""
        for block in self.blocks:
            if block['name'] == field_name:
                return block
        return {}

    def _normalize_size_of_targets(self, size_of: Any) -> List[str]:
        """Normalize size_of definition to a list of field names"""
        if isinstance(size_of, list):
            return [target for target in size_of if isinstance(target, str)]
        if isinstance(size_of, str):
            return [size_of]
        return []

    def _calculate_field_length(self, block: dict, value: Any) -> int:
        """
        Calculate the serialized length of a field in BITS.

        This method returns length in bits for all field types to support
        size fields that count in bits, bytes, or words.
        """
        if not block:
            return 0

        field_type = (block.get('type') or '').lower()

        # Bit fields - return size in bits directly
        if field_type == 'bits':
            return block.get('size', 0)

        # Fixed-size fields with explicit size attribute
        fixed_size = block.get('size')
        if isinstance(fixed_size, int):
            # For non-bit fields, size is in bytes - convert to bits
            if field_type != 'bits':
                return fixed_size * 8
            return fixed_size

        # Integer types - return size in bits
        if field_type.startswith('uint') or field_type.startswith('int'):
            type_name = block.get('type', 'uint8')
            byte_size = self._get_integer_info(type_name, block.get('endian', 'big'))['size']
            return byte_size * 8

        # Bytes field - calculate from value and convert to bits
        if field_type == 'bytes':
            if value is None:
                return 0
            if isinstance(value, (bytes, bytearray)):
                return len(value) * 8
            try:
                return len(bytes(value)) * 8
            except TypeError:
                return len(str(value).encode(block.get('encoding', 'utf-8'))) * 8

        # String field - calculate from value and convert to bits
        if field_type == 'string':
            if value is None:
                return 0
            if isinstance(value, bytes):
                # Treat already encoded strings as-is
                return len(value) * 8
            text = value if isinstance(value, str) else str(value)
            encoding = block.get('encoding', 'utf-8')
            return len(text.encode(encoding)) * 8

        # Fallback for unknown types
        if isinstance(value, bytes):
            return len(value) * 8
        if isinstance(value, str):
            return len(value.encode(block.get('encoding', 'utf-8'))) * 8
        return 0

    @staticmethod
    def _clone_default(value: Any) -> Any:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        if isinstance(value, list):
            return list(value)
        if isinstance(value, dict):
            return dict(value)
        return value
