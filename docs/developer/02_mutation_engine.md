# 2. The Mutation Engine

**Last Updated: 2026-01-26**

The heart of any fuzzer is its ability to generate new and interesting test cases. This fuzzer does not generate test cases from scratch. Instead, it uses a process of **selection and mutation**, starting with a set of known-good "seeds" and incrementally modifying them to explore the target's behavior. This process is orchestrated by the `FuzzOrchestrator` but the core logic for altering data resides in the **`MutationEngine`**.

## The Fuzzing Loop's Mutation Stage

Within the main fuzzing loop, the process for generating a single test case is as follows:

1.  **Select a Base Input**: An input is chosen from the corpus, either a seed or a follow-up message. In a stateful session, the input is chosen to match the protocol's current state.
2.  **Invoke the Mutation Engine**: The chosen input is passed to the `MutationEngine`'s `generate_test_case` method.
3.  **Apply Final Behaviors**: The mutated data is passed through a "behavior processor" which applies any final, deterministic transformations, such as updating a sequence number.
4.  **Queue for Execution**: The final test case is packaged and sent to the target.

## The `MutationEngine`

The `MutationEngine` (`core/engine/mutators.py`) is the primary component responsible for altering seed data. It supports three main modes of operation:

-   `byte_level`: The default mode. It applies simple, fast, protocol-agnostic mutations directly to the raw bytes of the seed.
-   `structure_aware`: An intelligent mode that uses knowledge of the protocol's structure (from a plugin) to create valid, complex mutations.
-   `hybrid`: A combination of both modes.

## Byte-Level Mutations

Byte-level mutators operate directly on the raw bytes of a seed without any understanding of the underlying protocol.

-   **`BitFlipMutator`**: Flips a small number of random bits.
-   **`ByteFlipMutator`**: Replaces a small number of random bytes with random values.
-   **`ArithmeticMutator`**: Performs simple arithmetic on a random 4-byte chunk of the data.
-   **`InterestingValueMutator`**: Overwrites a part of the data with "interesting" values known to cause edge cases (e.g., `0`, `-1`, `MAX_INT`).
-   **`HavocMutator`**: Applies a sequence of random, destructive actions, such as inserting, deleting, duplicating, or shuffling chunks of data.
-   **`SpliceMutator`**: Combines two different seeds from the corpus.

## Structure-Aware Mutations

Structure-aware mutation is the most powerful feature of the fuzzing engine. It allows the fuzzer to generate complex, valid test cases that can penetrate deep into an application's logic. This is handled by the `StructureAwareMutator` (`core/engine/structure_mutators.py`).

The process consists of four main steps:

1.  **Parse**: The raw bytes of a seed are parsed into a structured dictionary of fields and their values using the `ProtocolParser` and the plugin's `data_model`.
2.  **Select Field**: A random field marked as `mutable: True` is selected for mutation.
3.  **Mutate Field Value**: A type-aware mutation strategy is applied to the value of the chosen field.
4.  **Serialize**: The modified dictionary of fields is serialized back into a raw byte string. The `ProtocolParser` automatically recalculates any dependent fields, such as length prefixes or checksums.

This process ensures that the resulting test case is still structurally valid according to the protocol's rules.

### Structure-Aware Mutation Strategies

The `StructureAwareMutator` employs several strategies to mutate field values in a type-aware manner:

-   **`boundary_values`**: Replaces a field's value with known boundary values based on its type (e.g., `0`, `MAX_INT`, `MIN_INT` for integers; empty or max-size for byte arrays).
-   **`arithmetic`**: Applies arithmetic operations (adding or subtracting small values) to integer fields.
-   **`bit_flip_field`**: Flips a random bit within an integer or byte array field.
-   **`interesting_values`**: Replaces a field with "interesting" patterns (e.g., `../../../etc/passwd`, `' OR 1=1--`).
-   **`expand_field`**: Increases the size of variable-length fields.
-   **`shrink_field`**: Decreases the size of variable-length fields.
-   **`repeat_pattern`**: Fills a field with a repeating byte pattern (e.g., `\x00`, `\xFF`, `%s`).

The combination of simple, fast byte-level mutations and intelligent, complex structure-aware mutations allows the fuzzer to generate a highly diverse range of test cases, maximizing its chances of discovering vulnerabilities.
