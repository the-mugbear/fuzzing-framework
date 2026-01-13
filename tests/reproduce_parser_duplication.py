from core.engine.protocol_parser import ProtocolParser

def test_parser_serialization():
    # Model without checksum
    simple_model = {
        "blocks": [
            {"name": "header", "type": "uint8", "default": 0xFF},
            {"name": "payload", "type": "bytes", "size": 4, "default": b"TEST"}
        ]
    }
    
    parser = ProtocolParser(simple_model)
    fields = {"header": 0x01, "payload": b"DATA"}
    
    # This hits the duplicated logic in serialize()
    data = parser.serialize(fields)
    print(f"Serialized (simple): {data.hex()}")
    assert data == b"\x01DATA"

    # Model with checksum (hits serialize_with_checksums -> _serialize_without_checksum)
    checksum_model = {
        "blocks": [
            {"name": "len", "type": "uint8", "is_size_field": True, "size_of": "payload"},
            {"name": "payload", "type": "bytes", "default": b"Ping"},
            {"name": "crc", "type": "uint32", "is_checksum": True, "checksum_algorithm": "crc32"}
        ]
    }
    
    parser2 = ProtocolParser(checksum_model)
    fields2 = {"payload": b"1234"}
    
    data2 = parser2.serialize(fields2)
    print(f"Serialized (checksum): {data2.hex()}")
    # len=4 (0x04), payload="1234", crc=CRC32(0431323334)
    # Just ensuring it runs without error for now

if __name__ == "__main__":
    test_parser_serialization()
