#!/usr/bin/env python3
"""
Quick test of ProtocolParser with simple_tcp protocol
"""
import sys
sys.path.insert(0, '/home/charles/Projects/Fuzzing')

from core.engine.protocol_parser import ProtocolParser
from core.plugins import simple_tcp

# Test seeds from simple_tcp
seeds = [
    b"STCP\x00\x00\x00\x05\x01HELLO",  # AUTH
    b"STCP\x00\x00\x00\x04\x02TEST",   # DATA
    b"STCP\x00\x00\x00\x00\x03",       # QUIT
]

parser = ProtocolParser(simple_tcp.data_model)

print("Testing ProtocolParser with SimpleTCP protocol")
print("=" * 60)

for i, seed in enumerate(seeds, 1):
    print(f"\nTest {i}: {seed.hex()}")
    print(f"  Raw: {seed}")

    # Parse
    try:
        fields = parser.parse(seed)
        print(f"  Parsed: {fields}")

        # Serialize back
        reconstructed = parser.serialize(fields)
        print(f"  Serialized: {reconstructed.hex()}")

        # Verify round-trip
        if reconstructed == seed:
            print(f"  ✓ Round-trip PASSED")
        else:
            print(f"  ✗ Round-trip FAILED")
            print(f"    Expected: {seed.hex()}")
            print(f"    Got:      {reconstructed.hex()}")
    except Exception as e:
        print(f"  ✗ ERROR: {e}")

# Test field mutation and auto-fix
print("\n" + "=" * 60)
print("Testing auto-fix of length field")
print("=" * 60)

seed = seeds[0]  # AUTH message
fields = parser.parse(seed)
print(f"\nOriginal fields: {fields}")

# Mutate payload
fields['payload'] = b"WORLD!!!"  # Change from HELLO to WORLD!!!
print(f"After mutating payload: {fields}")

# Serialize - should auto-update length field
mutated = parser.serialize(fields)
print(f"Serialized: {mutated.hex()}")
print(f"Raw: {mutated}")

# Parse back to verify length was fixed
fields_check = parser.parse(mutated)
print(f"Parsed back: {fields_check}")

if fields_check['length'] == len(fields_check['payload']):
    print("✓ Length field AUTO-FIXED correctly!")
else:
    print(f"✗ Length mismatch: length={fields_check['length']}, payload={len(fields_check['payload'])}")
