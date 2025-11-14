import struct

from core.engine.protocol_parser import ProtocolParser


def test_size_field_accepts_multiple_targets():
    data_model = {
        "blocks": [
            {
                "name": "total_length",
                "type": "uint16",
                "is_size_field": True,
                "size_of": ["payload", "metadata", "footer"],
            },
            {
                "name": "payload",
                "type": "bytes",
                "max_size": 32,
            },
            {
                "name": "metadata",
                "type": "string",
                "encoding": "utf-8",
                "max_size": 16,
            },
            {
                "name": "footer",
                "type": "bytes",
                "size": 2,
                "default": b"\x00\x00",
            },
        ]
    }

    parser = ProtocolParser(data_model)
    payload = b"\xAA\xBB\xCC"
    metadata = "OK"
    footer = b"\xF0\x0F"

    serialized = parser.serialize(
        {
            "payload": payload,
            "metadata": metadata,
            "footer": footer,
        }
    )

    total_length = struct.unpack(">H", serialized[:2])[0]
    expected = len(payload) + len(metadata.encode("utf-8")) + len(footer)
    assert total_length == expected


def test_size_field_uses_defaults_for_missing_targets():
    data_model = {
        "blocks": [
            {
                "name": "segment_length",
                "type": "uint16",
                "is_size_field": True,
                "size_of": ["opcode", "checksum"],
            },
            {
                "name": "opcode",
                "type": "uint8",
                "default": 0x01,
            },
            {
                "name": "checksum",
                "type": "uint32",
                "default": 0,
            },
        ]
    }

    parser = ProtocolParser(data_model)
    serialized = parser.serialize({})
    segment_length = struct.unpack(">H", serialized[:2])[0]

    # opcode (1 byte) + checksum (4 bytes)
    assert segment_length == 5
