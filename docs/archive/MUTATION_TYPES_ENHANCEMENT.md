# Mutation Types Enhancement: Test Case Explorer

**Date**: 2025-11-10
**Status**: ✅ Complete

## Summary

The test case explorer now highlights **every mutation strategy explicitly** so contributors can compare structure-aware vs. byte-level outcomes at a glance. Each preview advertises its mutation type, mutators involved, and a short explanation, making it much easier to validate protocol plugins and debug edge cases.

## Mutation Strategy Cheat Sheet

| Strategy | Type | What it does | When to look for it | UI cues |
| --- | --- | --- | --- | --- |
| Structure-Aware | Protocol-aware | Rebuilds messages via the protocol grammar while tweaking individual fields deterministically | Validating schema coverage, confirming declarative behaviors fire | Green `Structure-Aware` badge + field-name note when detected |
| Bit Flip | Byte-level | Flips random bits anywhere in the payload | Stressing bitfields, toggling individual flags | Red `Byte-Level` badge + `bitflip` mutator pill |
| Byte Flip | Byte-level | Replaces random bytes with new values | Coarse corruption of opcodes/lengths | Red badge + `byteflip` pill |
| Arithmetic | Byte-level | Adds/subtracts small integers across 4-byte chunks | Testing counters, sequence numbers, and rolling IDs | Red badge + `arithmetic` pill |
| Interesting Values | Byte-level | Injects boundary constants (0, 0xFF, 0xFFFF, etc.) | Finding off-by-one issues and size handling bugs | Red badge + `interesting` pill |
| Havoc | Byte-level | Aggressively mixes inserts, deletes, and flips | Surfacing crashes quickly; chaos testing | Red badge + `havoc` pill |

## Mutation Strategy Details

### Structure-Aware Mutations
- **Scope**: Operates through the parser/data model, ensuring lengths, behaviors, and constraints stay consistent.
- **What to watch**: The UI surfaces the mutated field when `_detect_mutated_field` can pinpoint it, so protocol authors see exactly which block changed.
- **Why it matters**: Confirms declarative behaviors and field wiring before introducing raw corruption.

### Bit Flip
- Randomly flips individual bits; great for toggling flags or introducing subtle checksum corruption.
- Often produces minimally changed payloads, making diffs easy to reason about when debugging.

### Byte Flip
- Swaps entire bytes with random values, ignoring structure entirely.
- Useful for quickly validating how resilient parsers are to garbage opcodes or busted length prefixes.

### Arithmetic
- Applies ± small integers on four-byte windows.
- Tends to perturb counters, sequence numbers, and timestamps while leaving the rest intact—ideal for stateful protocols tracking monotonic IDs.

### Interesting Values
- Drops in canonical boundary values (0, 1, 255, 65535, etc.) at random offsets.
- Handy for discovering off-by-one errors, size truncations, or unhandled sentinel values.

### Havoc
- Kitchen-sink mutator that chains multiple low-level operations (insert/delete/flip) in one go.
- Expect noisy diffs; best for quickly shaking loose crashes once base coverage looks good.

## Problem Solved

**Before**: Only structure-aware mutations were rendered, so users could not directly compare byte-level behaviors or verify which mutators fired.

**After**: Every preview now surfaces:
- A mutation-type badge (Structure-Aware vs Byte-Level)
- Individual mutator pills (bitflip, arithmetic, havoc, etc.)
- A short description explaining what changed
- Alternating samples so both categories stay visible on each refresh

## Changes Made

### 1. Backend: Enhanced Data Models (`core/models.py`)

Added fields to `TestCasePreview`:
```python
mutation_type: Optional[str] = None  # "structure_aware" | "byte_level"
mutators_used: List[str] = []        # ["bitflip", "arithmetic", etc.]
description: Optional[str] = None    # Human-readable explanation
```

### 2. Backend: Updated Preview Endpoint (`core/api/server.py`)

**Imports**: Added byte-level mutators
```python
from core.engine.mutators import (
    ArithmeticMutator,
    BitFlipMutator,
    ByteFlipMutator,
    HavocMutator,
    InterestingValueMutator,
)
```

**Mutation Generation**: Now alternates between types
```python
# Initialize both types of mutators
structure_mutator = StructureAwareMutator(data_model)
byte_mutators = {
    "bitflip": BitFlipMutator(),
    "byteflip": ByteFlipMutator(),
    "arithmetic": ArithmeticMutator(),
    "interesting": InterestingValueMutator(),
    "havoc": HavocMutator()
}

# Alternate: even indices = structure-aware, odd indices = byte-level
for i in range(request.count):
    seed = random.choice(seeds)

    if i % 2 == 0:
        # Structure-aware mutation
        mutated = structure_mutator.mutate(seed)
        mutated_field = _detect_mutated_field(seed, mutated, parser, blocks)
        preview = _build_preview(
            i, mutated, parser, blocks,
            mode="mutated",
            mutation_type="structure_aware",
            mutators_used=["structure_aware"],
            description=f"Structure-aware mutation respecting protocol grammar{f' (field: {mutated_field})' if mutated_field else ''}"
        )
    else:
        # Byte-level mutation
        mutator_name = random.choice(list(byte_mutators.keys()))
        mutator = byte_mutators[mutator_name]
        mutated = mutator.mutate(seed)
        description = _get_mutator_description(mutator_name)
        preview = _build_preview(
            i, mutated, parser, blocks,
            mode="mutated",
            mutation_type="byte_level",
            mutators_used=[mutator_name],
            description=description
        )
```

**Helper Functions**:

```python
def _get_mutator_description(mutator_name: str) -> str:
    """Get human-readable description of what a mutator does"""
    descriptions = {
        "bitflip": "Bit flipping: Randomly flips individual bits in the message, potentially breaking field boundaries and creating invalid values",
        "byteflip": "Byte flipping: Replaces random bytes with random values, ignoring protocol structure",
        "arithmetic": "Arithmetic: Adds/subtracts small integers to 4-byte sequences, may corrupt length fields or counters",
        "interesting": "Interesting values: Injects boundary values (0, 255, 65535, etc.) at random positions",
        "havoc": "Havoc: Aggressive random mutations including insertions, deletions, and bit flips throughout the message"
    }
    return descriptions.get(mutator_name, f"Byte-level mutation: {mutator_name}")


def _detect_mutated_field(original: bytes, mutated: bytes, parser: ProtocolParser, blocks: List[dict]) -> Optional[str]:
    """Try to detect which field was mutated by comparing original and mutated messages"""
    try:
        original_fields = parser.parse(original)
        mutated_fields = parser.parse(mutated)

        for block in blocks:
            field_name = block['name']
            if field_name in original_fields and field_name in mutated_fields:
                # Skip computed fields (they change as a result of other changes)
                if block.get('is_size_field'):
                    continue

                if original_fields[field_name] != mutated_fields[field_name]:
                    return field_name
    except Exception:
        pass

    return None
```

### 3. Frontend: Enhanced UI Display (`core/ui/index.html`)

**Request More Samples**: Changed from 3 to 6 samples
```javascript
body: JSON.stringify({
    mode: 'mutations',
    count: 6  // Get 3 structure-aware + 3 byte-level
})
```

**Badge Rendering**:
```javascript
// Build mutator badges
let mutatorBadges = '';
if (preview.mutators_used && preview.mutators_used.length > 0) {
    const mutatorClass = preview.mutation_type === 'structure_aware' ?
        'mutator-badge-structure' : 'mutator-badge-byte';
    mutatorBadges = preview.mutators_used.map(m =>
        `<span class="mutator-badge ${mutatorClass}">${m}</span>`
    ).join('');
}

// Build mutation type badge
let typeBadge = '';
if (preview.mutation_type) {
    const typeClass = preview.mutation_type === 'structure_aware' ?
        'type-badge-structure' : 'type-badge-byte';
    const typeLabel = preview.mutation_type === 'structure_aware' ?
        'Structure-Aware' : 'Byte-Level';
    typeBadge = `<span class="type-badge ${typeClass}">${typeLabel}</span>`;
}

// Build description
let descriptionHtml = '';
if (preview.description) {
    descriptionHtml = `<div class="mutation-description">${preview.description}</div>`;
}
```

**CSS Styles**:
```css
.type-badge-structure {
    background: #1a3a2a;
    color: #4ade80;  /* Green */
    border: 1px solid #22543d;
}

.type-badge-byte {
    background: #3a1a1a;
    color: #fca5a5;  /* Red */
    border: 1px solid #7f1d1d;
}

.mutator-badge-structure {
    background: #1e3a26;
    color: #86efac;
}

.mutator-badge-byte {
    background: #3a1e1e;
    color: #f59e9e;
}

.mutation-description {
    margin-bottom: 8px;
    padding: 8px;
    background: #1a1a1a;
    border-left: 3px solid #0f8ecb;
    font-size: 11px;
    color: #999;
}

.sample-case-structure_aware {
    border-left: 3px solid #4ade80;  /* Green border */
}

.sample-case-byte_level {
    border-left: 3px solid #fca5a5;  /* Red border */
}
```

## Example Output

### API Response

```json
{
  "protocol": "kevin",
  "previews": [
    {
      "id": 0,
      "mode": "mutated",
      "mutation_type": "structure_aware",
      "mutators_used": ["structure_aware"],
      "description": "Structure-aware mutation respecting protocol grammar (field: command)",
      "hex_dump": "4B45564E...",
      "total_bytes": 14,
      "fields": [...]
    },
    {
      "id": 1,
      "mode": "mutated",
      "mutation_type": "byte_level",
      "mutators_used": ["arithmetic"],
      "description": "Arithmetic: Adds/subtracts small integers to 4-byte sequences, may corrupt length fields or counters",
      "hex_dump": "4B45564E...",
      "total_bytes": 14,
      "fields": [...]
    },
    {
      "id": 2,
      "mutation_type": "structure_aware",
      "mutators_used": ["structure_aware"],
      "description": "Structure-aware mutation respecting protocol grammar (field: payload)",
      ...
    },
    {
      "id": 3,
      "mutation_type": "byte_level",
      "mutators_used": ["bitflip"],
      "description": "Bit flipping: Randomly flips individual bits in the message, potentially breaking field boundaries and creating invalid values",
      ...
    }
  ]
}
```

### UI Display

The web UI now shows test cases with:

**Structure-Aware Mutations** (green):
```
┌─────────────────────────────────────────────────────┐
│ Case 1 · 14 bytes         [STRUCTURE-AWARE] [structure_aware] │
├─────────────────────────────────────────────────────┤
│ Structure-aware mutation respecting protocol        │
│ grammar (field: command)                            │
│                                                     │
│ Hex: 4B 45 56 4E 00 00 00 05 03 48 45 4C 4C 4F    │
│                                                     │
│ Fields:                                             │
│   magic: KEVN                                       │
│   length: 0x05 →payload ← automatically computed!  │
│   command: 0x03 ← mutated                          │
│   sequenceNumber: 0x0                               │
│   payload: HELLO                                    │
└─────────────────────────────────────────────────────┘
```

**Byte-Level Mutations** (red):
```
┌─────────────────────────────────────────────────────┐
│ Case 2 · 14 bytes              [BYTE-LEVEL] [arithmetic] │
├─────────────────────────────────────────────────────┤
│ Arithmetic: Adds/subtracts small integers to       │
│ 4-byte sequences, may corrupt length fields or     │
│ counters                                            │
│                                                     │
│ Hex: 4B 45 56 4E 00 00 00 85 01 48 45 4C 4C 4F    │
│                                                     │
│ Fields:                                             │
│   magic: KEVN                                       │
│   length: 0x85 ← CORRUPTED (should be 0x05)!      │
│   command: 0x01                                     │
│   sequenceNumber: 0x0                               │
│   payload: HELLO                                    │
└─────────────────────────────────────────────────────┘
```

## Key Differences Illustrated

### Structure-Aware Mutations
- **Respect field boundaries**
- **Maintain protocol validity**
- **Auto-update derived fields** (length, checksums)
- **Focus on one field at a time**
- Example: Change command from 0x01 → 0x03, length field updates automatically

### Byte-Level Mutations
- **Ignore protocol structure**
- **May break field boundaries**
- **Can corrupt derived fields**
- **Test parser robustness**
- Example: Add 128 to bytes 4-7, corrupting the length field

## Mutator Descriptions

### Structure-Aware
- Parses message into fields
- Mutates one field intelligently
- Serializes back with auto-fix
- Produces valid (but edge-case) messages

### Byte-Level Mutators

1. **bitflip**: Flips random bits
   - May corrupt multiple fields
   - Finds bit-level bugs
   - Example: `0x01` → `0x03` (bit 1 flipped)

2. **byteflip**: Replaces random bytes
   - Ignores field boundaries
   - Tests unexpected values
   - Example: Replace byte 8 with random value

3. **arithmetic**: Adds/subtracts integers
   - Corrupts 4-byte sequences
   - Finds integer overflow bugs
   - Example: `0x00000005` → `0x00000085` (+128)

4. **interesting**: Injects boundary values
   - 0, 255, 65535, etc.
   - Finds edge case bugs
   - Example: Replace bytes with `0xFF 0xFF 0xFF 0xFF`

5. **havoc**: Aggressive random changes
   - Insertions, deletions, bit flips
   - Maximum chaos
   - Example: Random modifications throughout message

## Benefits

### For Users
✅ **Understand mutation types** - See difference between structure-aware and byte-level
✅ **Verify correctness** - Confirm mutators are working as expected
✅ **Debug protocols** - Identify which mutations find bugs
✅ **Learn fuzzing** - Educational view of different strategies

### For Developers
✅ **Single source of truth** - Backend generates both types
✅ **Extensible** - Easy to add new mutators
✅ **Testable** - Can verify mutator behavior via API
✅ **Informative** - Descriptions explain what each mutator does

## Testing

```bash
# Test API endpoint
curl -X POST http://localhost:8000/api/plugins/kevin/preview \
  -H "Content-Type: application/json" \
  -d '{"mode": "mutations", "count": 6}' | \
  jq '.previews[] | {id, type: .mutation_type, mutators: .mutators_used}'

# Expected output: Alternating structure_aware and byte_level mutations
```

## Files Modified

1. **core/models.py** - Added mutation type fields to TestCasePreview
2. **core/api/server.py** - Enhanced preview endpoint with both mutation types
3. **core/ui/index.html** - Added badges, descriptions, and styling

## Future Enhancements

Potential additions:
- [ ] Let users filter by mutation type (show only structure-aware or only byte-level)
- [ ] Show statistics on which mutators find the most bugs
- [ ] Add "replay" button to re-run a specific mutation
- [ ] Show side-by-side comparison of same seed with different mutators
- [ ] Add custom mutators via plugin system

## Usage

### From Web UI
1. Open http://localhost:8000
2. Select a protocol from dropdown
3. Scroll to "Test Case Samples" → "Mutation Previews"
4. See alternating green (structure-aware) and red (byte-level) test cases
5. Read descriptions to understand what each mutator does

### From API
```bash
# Get mix of both types
curl -X POST http://localhost:8000/api/plugins/kevin/preview \
  -H "Content-Type: application/json" \
  -d '{"mode": "mutations", "count": 6}'
```

## Conclusion

Users can now see exactly how different mutation strategies affect their protocol messages, helping them:
- Understand fuzzing techniques
- Verify protocol correctness
- Debug issues with specific mutators
- Choose appropriate mutation strategies for their target

The test case explorer is now a comprehensive debugging tool showing both intelligent (structure-aware) and chaotic (byte-level) mutations.
