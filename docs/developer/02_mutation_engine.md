# 2. The Mutation Engine

**Last Updated: 2026-02-06**

This document details the fuzzer's mutation engine, the core component responsible for generating novel test cases from an initial set of seeds.

## The Fuzzing Lifecycle's Mutation Stage

Within the main fuzzing loop, the process for generating a single test case involves several key steps, with a critical distinction for orchestrated sessions.

1.  **Select a Base Input**: An input is chosen from the corpus for the current fuzzing stage.
2.  **Context Injection (Orchestrated Sessions Only)**: Before any mutation occurs, the `FuzzOrchestrator` inspects the `data_model` for fields with a `from_context` attribute. It injects the required values (e.g., a `session_token`) from the `ProtocolContext` into the parsed structure of the test case.
3.  **Invoke the Mutation Engine**: The test case (now with context values injected) is passed to the `MutationEngine`'s `generate_test_case` method.
4.  **Apply Final Behaviors**: The mutated data is passed through a "behavior processor" which applies any final, deterministic transformations (e.g., updating a sequence number).
5.  **Queue for Execution**: The final test case is packaged and sent to the target.

## The `MutationEngine`

The `MutationEngine` (`core/engine/mutators.py`) is the primary component for altering test case data. It supports three main modes of operation:

-   `byte_level`: Applies simple, fast, protocol-agnostic mutations directly to the raw bytes.
-   `structure_aware`: Uses knowledge of the protocol's structure to create valid, complex mutations.
-   `hybrid`: A configurable mix of both modes.

## Byte-Level Mutations

Byte-level mutators operate directly on the raw bytes of a test case without any understanding of the underlying protocol. They are excellent for finding parser bugs.

-   **`BitFlipMutator`**: Flips a small number of random bits.
-   **`ByteFlipMutator`**: Replaces a small number of random bytes.
-   **`HavocMutator`**: Applies a sequence of random, destructive actions, such as inserting, deleting, or shuffling chunks of data.
-   **And others**: Includes arithmetic mutators, "interesting value" injectors, etc.

## Structure-Aware Mutations

This is the most powerful feature of the engine, handled by the `StructureAwareMutator` (`core/engine/structure_mutators.py`). It enables the fuzzer to generate complex, valid test cases that can penetrate deep into an application's logic.

The process consists of four steps:

1.  **Parse**: The raw bytes are parsed into a structured dictionary of fields using the `ProtocolParser` and the plugin's `data_model`.
2.  **Select Field**: A random field marked as `mutable: True` is selected for mutation.
3.  **Mutate Field Value**: A type-aware mutation strategy (e.g., boundary values, arithmetic) is applied to the value of the chosen field.
4.  **Serialize**: The modified dictionary is serialized back into raw bytes. The `ProtocolParser` automatically recalculates dependent fields like length prefixes or checksums.

### The Importance of `mutable: False`
In a standard session, `mutable: False` is used to protect static data like magic headers. In an **Orchestrated Session**, it plays a more critical role.

**Fields populated via `from_context` should almost always be marked `mutable: False`**.

```python
# In a fuzz_target plugin's data_model
{
    "name": "session_token",
    "type": "uint32",
    "from_context": "session_token", # Injected by the orchestrator
    "mutable": False                 # Prevents the mutation engine from corrupting it
}
```

If this field were mutable, the `StructureAwareMutator` could randomly select it and change the session token, invalidating the session and wasting the effort of the `bootstrap` stage. By marking it as non-mutable, you ensure the integrity of the session while allowing the fuzzer to focus on other, more productive fields.

### Structure-Aware Mutation Strategies

-   **`boundary_values`**: Tests edge cases like `0`, `MAX_INT`, etc.
-   **`arithmetic`**: Adds or subtracts small values from integers.
-   **`bit_flip_field`**: Flips random bits *within* the selected field's boundaries.
-   **`expand_field` / `shrink_field`**: Changes the size of variable-length fields.
-   **`repeat_pattern`**: Fills a field with a repeating byte pattern (e.g., `A`, `\x00`, `%s`).

The combination of simple, fast byte-level mutations and intelligent, complex structure-aware mutations allows the fuzzer to generate a highly diverse range of test cases, maximizing its chances of discovering vulnerabilities in both the parser and the application logic.
