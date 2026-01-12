# Mutation Strategies Explained

## Overview

The fuzzer supports two fundamentally different mutation approaches that can be used independently or together:

1. **Structure-Aware Mutation** - Intelligent, field-level mutations that respect protocol grammar
2. **Byte-Level Mutations** - Blind, raw byte mutations that ignore protocol structure

---

## Structure-Aware Mutation

### What It Does

Structure-aware mutation is a **single, intelligent strategy** that:

1. **Parses** the message using the protocol definition (`data_model`)
2. **Randomly selects ONE mutable field** from the protocol
3. **Applies an intelligent mutation strategy** to that field:
   - `boundary_values` (25% weight) - Tests edge cases like 0, 1, MAX, MIN
   - `arithmetic` (20%) - Adds/subtracts small values to integers
   - `bit_flip_field` (15%) - Flips bits within the field
   - `interesting_values` (20%) - Uses known problematic values
   - `expand_field` (8%) - Increases variable-length field size
   - `shrink_field` (7%) - Decreases variable-length field size
   - `repeat_pattern` (5%) - Fills field with repeating pattern
4. **Auto-fixes dependent fields** (like length fields)
5. **Serializes back to valid bytes**

### Field Selection Logic

**From `structure_mutators.py:69-76`:**
```python
# Get all fields where mutable: True (default)
mutable_fields = self._get_mutable_fields()

# Randomly pick ONE field
target_block = random.choice(mutable_fields)
field_name = target_block['name']
```

**Fields are mutable by default** unless explicitly marked `mutable: False` in the protocol definition:

```python
# Example protocol definition
data_model = {
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "mutable": False},  # ← Never mutated
        {"name": "length", "type": "uint32", "is_size_field": True},      # ← Mutable (auto-fixed)
        {"name": "payload", "type": "bytes", "max_size": 1024}            # ← Mutable
    ]
}
```

In this example:
- **"magic"** - Never selected (mutable: False)
- **"length"** - Can be selected, but auto-fixed after payload changes
- **"payload"** - Can be selected

Each time you click "Structure-Aware", it **randomly picks ONE of these mutable fields** and applies **ONE mutation strategy** to it.

### Why Use Structure-Aware?

✅ **Maintains message validity** - Messages are more likely to pass parsing checks
✅ **Efficient field exploration** - Systematically tests field boundaries
✅ **Automatic length/checksum fixing** - Dependent fields update automatically
✅ **Smart value selection** - Uses protocol-defined known values when available
✅ **Good for stateful protocols** - Valid messages reach deeper protocol states

❌ **May miss cross-field bugs** - Only mutates one field at a time
❌ **Constrained** - Won't explore completely invalid messages
❌ **Depends on accurate data_model** - Requires protocol definition

### Example: Structure-Aware Mutation

**Before:**
```
magic:   STCP (mutable: False)
length:  5    (uint32, auto-fixed)
payload: HELLO
```

**Apply Structure-Aware → Randomly selects "payload" → Applies "expand_field":**

```
magic:   STCP              (unchanged)
length:  15                (auto-fixed to match new payload size)
payload: HELLOHELLOHELLO  (expanded 3x)
```

**Note:** The "length" field was automatically updated even though "payload" was the selected field.

---

## Byte-Level Mutations

### What They Do

Byte-level mutators are **blind, dumb strategies** that:

1. Treat the message as **raw bytes**
2. **Don't understand** field boundaries or types
3. Mutate bytes at **random positions**
4. **Can break** message validity

Each byte-level mutator is a **separate strategy**:

### BitFlip
- Flips individual bits (0→1 or 1→0)
- Mutates ~1% of total bits by default
- Can subtly corrupt any field

### ByteFlip
- Replaces random bytes with random values (0-255)
- Mutates ~5% of bytes by default
- More aggressive than BitFlip

### Arithmetic
- Picks random 4-byte sequence
- Interprets as uint32
- Adds/subtracts delta: [-128, -64, -32, -16, -8, -1, 1, 8, 16, 32, 64, 128]
- Can overflow into adjacent fields

### Interesting Values
- Picks random position
- Injects boundary values:
  - 8-bit: 0, 1, 127, 128, 255
  - 16-bit: 0, 1, 255, 256, 32767, 32768, 65535
  - 32-bit: 0, 1, 65535, 65536, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF
- May partially overwrite multiple fields

### Havoc
- **Aggressive multi-mutation**
- Applies 2-10 random operations:
  - Insert random bytes
  - Delete bytes
  - Duplicate chunks
  - Shuffle chunks
- Can completely destroy message structure

### Splice
- Combines parts of two different base messages
- Picks random split points in each message
- Creates: `message1[:split1] + message2[split2:]`
- Requires 2+ base messages

### Why Use Byte-Level?

✅ **Finds unexpected bugs** - Tests combinations structure-aware won't try
✅ **No protocol knowledge needed** - Works without data_model
✅ **Explores invalid states** - Tests error handling paths
✅ **Simple and fast** - No parsing overhead

❌ **Breaks message validity** - Most mutations rejected by parsers
❌ **Inefficient** - High rejection rate
❌ **Doesn't respect dependencies** - Breaks length fields, checksums
❌ **Hard to reproduce** - Random positions mean less predictable behavior

### Example: Byte-Level Mutation

**Before:**
```
Hex: 53 54 43 50 00 00 00 05 48 45 4C 4C 4F
     |  STCP  |  length=5  |   HELLO      |
```

**Apply BitFlip → Randomly flips bit at byte offset 6:**

```
Hex: 53 54 43 50 00 00 08 05 48 45 4C 4C 4F
     |  STCP  |  length=   |   HELLO      |
                     ↑↑
                  Changed 0x00 → 0x08
```

**Result:** Length field now says 2053 instead of 5 - **invalid message!**

---

## Comparison Table

| Aspect | Structure-Aware | Byte-Level |
|--------|----------------|------------|
| **Field Understanding** | ✅ Yes - parses message | ❌ No - treats as raw bytes |
| **Field Selection** | 🎲 Random single field | 🎲 Random byte positions |
| **Message Validity** | ✅ Maintains validity | ❌ Often breaks validity |
| **Auto-Fix Lengths** | ✅ Yes | ❌ No |
| **Mutation Count** | 1 field per click | Varies (BitFlip: ~1% of bits, Havoc: 2-10 operations) |
| **Protocol Knowledge** | ⚠️ Requires data_model | ✅ No requirements |
| **Efficiency** | ✅ High - valid messages reach deeper states | ❌ Low - most rejected early |
| **Bug Types Found** | Logic bugs, boundary issues | Parser crashes, unexpected states |

---

## Mutation Modes (Fuzzing Sessions)

When running a **fuzzing session** (not the workbench), the engine supports three modes:

### 1. `structure_aware` Mode
- **Only** uses structure-aware mutation
- Every test case is a valid, field-level mutation
- Best for stateful protocols requiring valid messages

### 2. `byte_level` Mode (Default)
- **Only** uses byte-level mutators
- Classic blind fuzzing approach
- Best for finding parser bugs

### 3. `hybrid` Mode
- **Mixes both** approaches based on weight
- `structure_aware_weight: 30` means 30% structure-aware, 70% byte-level
- Balances efficiency and exploration

**Configure via `core/config.py`:**
```python
mutation_mode: str = "byte_level"  # or "structure_aware" or "hybrid"
structure_aware_weight: int = 30   # Used in hybrid mode
```

---

## Workbench Behavior

In the **Mutation Workbench**, each button applies **one mutation**:

- **"Structure-Aware" button:**
  1. Parses message
  2. Picks ONE random mutable field
  3. Applies ONE mutation strategy to that field
  4. Shows exactly what changed in diff view

- **"BitFlip", "ByteFlip", etc. buttons:**
  1. Treats message as raw bytes
  2. Mutates random positions
  3. Shows diff of byte-level changes

You can **chain mutations** by clicking multiple buttons:
1. Click "Structure-Aware" → mutates one field
2. Click "BitFlip" → corrupts some bytes
3. Click "Structure-Aware" again → mutates a different field (random)
4. Timeline shows all three mutations

---

## Detailed: Structure-Aware Field Selection

### The Algorithm

**From `structure_mutators.py:360-370`:**
```python
def _get_mutable_fields(self) -> List[dict]:
    """Get list of fields that can be mutated."""
    mutable = []
    for block in self.blocks:
        if block.get('mutable', True):  # ← Default is True!
            mutable.append(block)
    return mutable
```

Then in `mutate()`:
```python
target_block = random.choice(mutable_fields)
```

### Controlling Which Fields Are Mutated

**Mark fields as non-mutable:**
```python
data_model = {
    "blocks": [
        {"name": "header", "type": "bytes", "size": 4, "mutable": False},  # ← Never selected
        {"name": "command", "type": "uint8", "mutable": True},             # ← Can be selected
        {"name": "payload", "type": "bytes", "max_size": 1024}             # ← Can be selected (default)
    ]
}
```

### Field Selection Is Random Every Time

**Important:** Each time you click "Structure-Aware", the field is re-selected randomly:

```
Click 1: Randomly selects "payload" → mutates to "AAAA..."
Click 2: Randomly selects "command" → mutates to 0xFF
Click 3: Randomly selects "payload" again → mutates to "\x00\x00"
```

You **cannot control** which field will be mutated on each click. It's intentionally random to explore different fields over many test cases.

---

## Example: Combining Both Approaches

### Scenario: Testing SimpleTCP Protocol

**Protocol Definition:**
```python
data_model = {
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"STCP", "mutable": False},
        {"name": "length", "type": "uint32", "endian": "big", "is_size_field": True, "size_of": "payload"},
        {"name": "command", "type": "uint8", "values": {0x01: "PING", 0x02: "PONG"}},
        {"name": "payload", "type": "bytes", "max_size": 1024}
    ]
}
```

**Mutable fields:** length, command, payload (magic is excluded)

### Test Case 1: Structure-Aware
```
Base:   STCP | 00 00 00 05 | 01 | HELLO
Apply:  Structure-Aware
Result: STCP | 00 00 00 00 | 01 | (empty)
Field:  payload was randomly selected and shrunk to empty
Effect: Length auto-fixed to 0
Status: ✅ Valid message - tests empty payload edge case
```

### Test Case 2: ByteFlip
```
Base:   STCP | 00 00 00 05 | 01 | HELLO
Apply:  ByteFlip
Result: STCP | 00 00 FF 05 | 01 | HELLO
Bytes:  Random byte at offset 6 changed to 0xFF
Effect: Length field corrupted to 65285
Status: ❌ Invalid - length mismatch, tests parser robustness
```

### Test Case 3: Structure-Aware → ByteFlip (chained)
```
Base:     STCP | 00 00 00 05 | 01 | HELLO
Step 1:   Structure-Aware → randomly selects "command"
          STCP | 00 00 00 05 | FF | HELLO  (invalid command)
Step 2:   ByteFlip
          STCP | 00 AA 00 05 | FF | HELLO  (corrupted length too)
Status:   ❌ Invalid message with invalid command and corrupted length
Finding:  Tests if server crashes on invalid command + length combo
```

---

## Best Practices

### For Mutation Workbench (Interactive Testing)

**Use Structure-Aware when:**
- ✅ Testing field boundary conditions
- ✅ Need valid messages to reach deep protocol states
- ✅ Debugging specific field behaviors
- ✅ Building reproducible test cases

**Use Byte-Level when:**
- ✅ Testing parser robustness
- ✅ Looking for crashes/memory corruption
- ✅ Exploring completely unexpected inputs
- ✅ Don't have a complete data_model

**Chaining Strategy:**
1. Start with Structure-Aware to build interesting valid state
2. Apply byte-level to corrupt it in subtle ways
3. Review diff to understand what changed
4. Send to target and observe behavior

### For Fuzzing Sessions (Automated)

**Use `structure_aware` mode when:**
- Protocol requires valid authentication/handshake
- Target parser is robust and rejects most invalid input
- You want to test business logic bugs
- You have a detailed data_model

**Use `byte_level` mode when:**
- Looking for parser vulnerabilities
- Protocol is simple or stateless
- Want maximum code coverage quickly
- Don't have data_model

**Use `hybrid` mode when:**
- Want both deep state exploration AND parser testing
- Have some data_model but not complete
- Balanced approach for unknown targets
- Adjust weight based on what's finding more bugs

---

## Common Questions

### Q: Why does Structure-Aware sometimes make no changes?

**A:** If the randomly selected field is already at a boundary value, and the randomly selected strategy tries to set it to the same value, no change occurs. The diff viewer will show "0 bytes changed" and warn you.

**Example:**
- Field "length" is already 0
- Strategy "boundary_values" is selected
- It tries to set length to 0 again
- No change occurs

### Q: Can I control which field Structure-Aware mutates?

**A:** No, field selection is intentionally random to ensure broad exploration. However, you can:
- Mark unwanted fields as `mutable: False` in data_model
- Use manual field editing in the workbench to target specific fields
- Chain multiple Structure-Aware mutations and keep the one that mutated your desired field

### Q: Why do byte-level mutations sometimes change nothing?

**A:** Possible reasons:
- BitFlip flipped a bit that was already 0 or 1, resulting in no visual change in hex
- ByteFlip selected the same random value that was already there
- Havoc delete/insert operations cancelled each other out

### Q: How many bytes does each byte-level mutator change?

**A:** Varies by mutator:
- **BitFlip:** ~1% of bits (so ~0.125% of bytes, but changes bits within bytes)
- **ByteFlip:** ~5% of bytes
- **Arithmetic:** Exactly 4 bytes (interpreted as uint32)
- **Interesting:** 1, 2, or 4 bytes depending on size chosen
- **Havoc:** Variable - 2 to 10 operations affecting anywhere from a few to hundreds of bytes
- **Splice:** Depends on random split points - can be anywhere from 0% to 100% of message

### Q: What does "auto-fixing" mean?

**A:** When Structure-Aware mutates a field, it checks for dependent fields:
- **Length fields** (`is_size_field: True`) are recalculated based on actual data size
- **Checksums** (if implemented) are recomputed
- This happens automatically during serialization

**Example:**
```python
# Before mutation
payload: "HELLO"      (5 bytes)
length: 5             (correct)

# After Structure-Aware expands payload
payload: "HELLOHELLO" (10 bytes)
length: 10            (auto-fixed!)
```

---

## Conclusion

**Structure-Aware** and **Byte-Level** mutations serve different purposes:

- **Structure-Aware** = Smart, single-field, validity-maintaining
- **Byte-Level** = Dumb, multi-position, validity-breaking

Both are valuable:
- Structure-Aware finds **logic bugs** in valid message handling
- Byte-Level finds **parser bugs** in invalid message handling

The workbench lets you apply each mutation individually to understand their effects, while fuzzing sessions can mix them automatically based on configuration.

**Key Takeaway:** "Structure-Aware" isn't just another mutation like BitFlip - it's a fundamentally different **approach** that parses, selects a field, and mutates intelligently. The UI groups it separately to emphasize this distinction.
