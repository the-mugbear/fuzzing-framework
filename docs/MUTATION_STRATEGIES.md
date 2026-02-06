# Mutation Strategies Guide

**Last Updated: 2026-02-06**

This guide explains the different mutation strategies used by the fuzzer. Understanding these strategies is key to designing effective fuzzing campaigns.

## 1. Core Mutation Approaches

The fuzzer supports three fundamentally different approaches to mutation:

1.  **Structure-Aware Mutation**: An intelligent, field-level approach that understands and respects the protocol's grammar as defined in the `data_model`.
2.  **Byte-Level Mutations**: A "dumb" or "blind" approach that treats the message as raw bytes and mutates them without any knowledge of the protocol's structure.
3.  **Enumeration Testing**: A systematic, deterministic approach that tests boundary values for every mutable field, ensuring complete coverage of edge cases.

---

## 2. Structure-Aware Mutation

This is the most sophisticated mutation strategy. It parses a message into its constituent fields and intelligently mutates one field at a time before re-serializing it into a valid message.

### How It Works
1.  **Parses** the message using the `data_model`.
2.  **Randomly selects ONE mutable field** (a field not marked `mutable: False`).
3.  **Applies an intelligent mutation** to that single field (e.g., tests boundary values, flips bits *within the field*, adds/subtracts small values).
4.  **Auto-fixes dependent fields**, such as recalculating length or checksum fields.
5.  **Serializes** the message back into valid bytes.

### Why Use It?
-   **High Efficiency**: Produces a high ratio of valid messages that can penetrate deep into the target's logic instead of being rejected by the parser.
-   **Stateful Fuzzing**: Essential for stateful protocols where maintaining a valid session is crucial.
-   **Finds Logic Bugs**: Excellent at finding bugs in business logic by providing valid-but-unexpected values.

### Controlling Structure-Aware Mutations
You can control which fields are mutated by marking them as non-mutable in your plugin:
```python
data_model = {
    "blocks": [
        # This field will NEVER be selected for mutation
        {"name": "magic_header", "type": "bytes", "size": 4, "mutable": False},

        # This field CAN be selected
        {"name": "command", "type": "uint8"},
    ]
}
```

---

## 3. Byte-Level Mutations

Byte-level mutators are simple, fast, and require no knowledge of the protocol. They are excellent for finding parser bugs and memory corruption issues.

-   **BitFlip**: Flips a small percentage of random bits (e.g., `0` -> `1`).
-   **ByteFlip**: Replaces a small percentage of random bytes with random values.
-   **Havoc**: A highly aggressive strategy that applies multiple random operations: inserting, deleting, duplicating, and shuffling chunks of bytes. It is very effective at creating chaos and breaking parsers.
-   **And more...**: Includes arithmetic mutators, interesting value injectors, etc.

### Why Use It?
-   **Finds Parser Bugs**: The primary way to find vulnerabilities in the code that parses and validates messages.
-   **No Protocol Knowledge Needed**: Works even without a `data_model`.
-   **Simplicity and Speed**: Very fast, as no parsing is required.

---

## 4. Enumeration Testing (Deterministic Fuzzing)

Enumeration modes provide **systematic, deterministic testing** of boundary values. Unlike random mutation, enumeration generates a finite, predictable set of test cases that exhaustively cover edge cases.

### How It Works
1.  **Analyzes** the `data_model` to find all mutable fields.
2.  **Calculates boundary values** for each field based on type (e.g., 0, 1, 127, 128, 255 for uint8).
3.  **Generates test cases** systematically, varying one or more fields at a time.
4.  **Auto-fixes dependent fields** (lengths, checksums) just like structure-aware mode.

### Enumeration Modes

| Mode | Description | Test Cases | Use Case |
|------|-------------|------------|----------|
| `enumeration` | Varies ONE field at a time through its boundary values | Linear: O(fields × values) | Quick boundary check |
| `enumeration_pairwise` | Tests all PAIRS of boundary values | Quadratic: O(fields² × values²) | Interaction bugs |
| `enumeration_full` | Full permutation of ALL boundary values | Exponential: O(values^fields) | Complete coverage |

### Example: A Protocol with 3 Fields

For a protocol with `cmd` (uint8), `flags` (uint8), and `len` (uint16), each with ~5 boundary values:

| Mode | Approximate Test Cases |
|------|------------------------|
| `enumeration` | 3 fields × 5 values = ~15 tests |
| `enumeration_pairwise` | 3×2 pairs × 25 combinations = ~75 tests |
| `enumeration_full` | 5 × 5 × 5 = 125 tests |

### Why Use It?
-   **Guaranteed Coverage**: Every boundary value is tested, no randomness.
-   **Reproducible**: Same test cases every time.
-   **Finite**: Session completes when all cases are tested.
-   **Best for QA**: Ideal for regression testing and validation.

### Behavior When Exhausted
When enumeration completes all test cases, the session:
1.  Logs `enumeration_complete` with total count
2.  Falls back to byte-level mutations for continued fuzzing
3.  Reports exhaustion in session metadata

---

## 5. Mutator Selection

You can customize which mutation algorithms are applied during a session using the **Customize Mutators** panel in the UI or the `enabled_mutators` API parameter.

### Available Byte-Level Mutators

| Mutator | Description | Example |
|---------|-------------|---------|
| `bitflip` | Flips random bits (0→1, 1→0) | `0x80` → `0x81` (bit 0 flipped) |
| `byteflip` | Replaces bytes with random values | `0x41` → `0xF3` |
| `arithmetic` | Adds/subtracts small integers | `0x0100` → `0x00FF` (-1) |
| `interesting` | Injects boundary values (0, MAX, etc.) | Field → `0xFFFFFFFF` |
| `havoc` | Aggressive chaos: insert, delete, shuffle | Completely transformed |
| `splice` | Combines parts of different seeds | seed1[:50] + seed2[50:] |

### Structure-Aware Strategy Mapping

When using `structure_aware` or `hybrid` mode, your mutator selections are mapped to equivalent structure-aware strategies:

| Selected Mutator | Structure-Aware Strategies |
|------------------|---------------------------|
| `bitflip` | `bit_flip_field` |
| `byteflip` | `bit_flip_field` |
| `arithmetic` | `arithmetic` |
| `interesting` | `interesting_values`, `boundary_values` |
| `havoc` | `expand_field`, `shrink_field`, `repeat_pattern` |
| `splice` | (no equivalent - requires multiple seeds) |

**Example**: If you select only `bitflip` in `structure_aware` mode, only the `bit_flip_field` strategy will be used. The fuzzer will parse each message, select a mutable field, and flip random bits within that field while keeping the message structure valid.

### Best Practice: Focused Mutation

For targeted testing, disable mutators that don't apply to your goal:

-   **Testing integer overflow?** Enable only `arithmetic` and `interesting`
-   **Testing parser robustness?** Enable `havoc` and `byteflip`
-   **Testing bit flags?** Enable only `bitflip`

---

## 6. Mutation Modes in Fuzzing Sessions

When you run a fuzzing session, you can choose how these approaches are combined using the `mutation_mode`.

### Random Mutation Modes

#### **`structure_aware` Mode**
-   **What it does**: Exclusively uses the structure-aware mutation engine.
-   **Best for**: Stateful protocols, targets with robust parsers, or when you want to focus on logic bugs.
-   **Mutator selection**: Respects your mutator selection (mapped to structure-aware strategies).

#### **`byte_level` Mode**
-   **What it does**: Exclusively uses the byte-level mutators (BitFlip, Havoc, etc.).
-   **Best for**: Finding parser bugs, testing stateless protocols, or when you don't have a detailed `data_model`.
-   **Mutator selection**: Uses exactly the mutators you select.

#### **`hybrid` Mode (Default)**
-   **What it does**: Mixes both approaches. The `structure_aware_weight` determines the balance (e.g., 70 means 70% structure-aware, 30% byte-level).
-   **Best for**: A balanced approach that tests both the parser and the application logic. This is a great general-purpose choice.
-   **Mutator selection**: Applied to both structure-aware and byte-level mutations.

### Deterministic Enumeration Modes

#### **`enumeration` Mode**
-   **What it does**: Systematically tests boundary values, varying ONE field at a time.
-   **Best for**: Quick boundary value coverage, regression testing.
-   **Test cases**: Linear count based on fields × values per field.
-   **Note**: Mutator selection is ignored (uses fixed boundary value strategy).

#### **`enumeration_pairwise` Mode**
-   **What it does**: Tests all PAIRS of boundary values across fields.
-   **Best for**: Finding bugs that require two specific values to interact.
-   **Test cases**: Quadratic growth. Use with caution on large protocols.

#### **`enumeration_full` Mode**
-   **What it does**: Full permutation of all boundary values across all fields.
-   **Best for**: Maximum coverage when test case count is manageable.
-   **Test cases**: Exponential growth. **WARNING**: Can generate millions of tests!

### Mode Selection Guide

| Goal | Recommended Mode | Why |
|------|------------------|-----|
| General fuzzing | `hybrid` | Balanced coverage |
| Logic bug hunting | `structure_aware` | Valid messages reach deep code |
| Parser stress testing | `byte_level` | Maximum corruption |
| Boundary value coverage | `enumeration` | Systematic, finite |
| Interaction bugs | `enumeration_pairwise` | Tests field combinations |
| Complete coverage | `enumeration_full` | Every combination (small protocols only) |

---

## 7. Mutations in Orchestrated Sessions

When using an **Orchestrated Session** defined by a `protocol_stack`, mutation strategies are applied to the messages defined in the **current stage**.

> **Note**: Enumeration modes are fully supported in orchestrated sessions. The enumeration generator respects the `fuzz_target` stage's data model and generates systematic test cases within the orchestration flow.

-   The `bootstrap` and `teardown` stages typically send static, valid messages and **do not involve mutation**. Their goal is to set up or tear down the session state.
-   The **`fuzz_target` stage is where the fuzzing and mutations occur**. The chosen `mutation_mode` will be applied to the messages defined in the `fuzz_target` stage's plugin.

### Best Practice: `from_context` and `mutable: False`

This is a critical best practice for orchestrated sessions. When a field in your `fuzz_target` plugin gets its value from the `ProtocolContext`, you should almost always mark it as non-mutable.

**Why?** The `from_context` value is often a session token, sequence number, or other critical piece of data required for the session to remain valid. If the fuzzer mutates this value, the target will likely reject the message and possibly terminate the session, defeating the purpose of the orchestration.

**Correct Implementation:**
```python
# In your fuzz_target plugin's data_model
data_model = {
    "blocks": [
        {
            "name": "session_token",
            "type": "uint32",
            "from_context": "session_token", # Gets value from context
            "mutable": False                 # PREVENT FUZZER FROM CHANGING IT
        },
        {
            "name": "fuzzed_payload",
            "type": "bytes",
            "max_size": 1024,
            "mutable": True # This is the field we actually want to fuzz
        }
    ]
}
```
By doing this, you ensure that the session remains valid while the fuzzer focuses its efforts on the parts of the message that are safe and productive to mutate.
