# Mutation Strategies Guide

**Last Updated: 2026-01-30**

This guide explains the different mutation strategies used by the fuzzer. Understanding these strategies is key to designing effective fuzzing campaigns.

## 1. Core Mutation Approaches

The fuzzer supports two fundamentally different approaches to mutation, which can be used independently or together:

1.  **Structure-Aware Mutation**: An intelligent, field-level approach that understands and respects the protocol's grammar as defined in the `data_model`.
2.  **Byte-Level Mutations**: A "dumb" or "blind" approach that treats the message as raw bytes and mutates them without any knowledge of the protocol's structure.

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

## 4. Mutation Strategies in Fuzzing Sessions

When you run a fuzzing session, you can choose how these approaches are combined using the `mutation_mode`.

### **`structure_aware` Mode**
-   **What it does**: Exclusively uses the structure-aware mutation engine.
-   **Best for**: Stateful protocols, targets with robust parsers, or when you want to focus on logic bugs.

### **`byte_level` Mode**
-   **What it does**: Exclusively uses the byte-level mutators (BitFlip, Havoc, etc.).
-   **Best for**: Finding parser bugs, testing stateless protocols, or when you don't have a detailed `data_model`.

### **`hybrid` Mode (Default)**
-   **What it does**: Mixes both approaches. The `structure_aware_weight` in `core/config.py` determines the balance (e.g., a weight of `70` means 70% structure-aware, 30% byte-level).
-   **Best for**: A balanced approach that tests both the parser and the application logic. This is a great general-purpose choice.

---

## 5. Mutations in Orchestrated Sessions

When using an **Orchestrated Session** defined by a `protocol_stack`, mutation strategies are applied to the messages defined in the **current stage**.

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
