# 2. The Mutation Engine

The heart of any fuzzer is its ability to generate new and interesting test cases. This fuzzer does not generate test cases from scratch. Instead, it uses a process of **selection and mutation**, starting with a set of known-good "seeds" and incrementally modifying them to explore the target's behavior. This process is orchestrated by the `FuzzOrchestrator` but the core logic for altering data resides in the **`MutationEngine`**.

## The Fuzzing Loop's Mutation Stage

Within the main fuzzing loop (`_run_fuzzing_loop` in `FuzzOrchestrator`), the process for generating a single test case is as follows:

1.  **Select a Base Seed**: A seed is chosen from the corpus. In a simple stateless session, this might be a simple round-robin selection. In a stateful session, a seed is intelligently chosen that matches the protocol's current state requirements.
2.  **Invoke the Mutation Engine**: The chosen seed is passed to the `MutationEngine`'s `generate_test_case` method. The engine applies one or more mutation strategies to create a new, unique test case.
3.  **Apply Final Behaviors**: The mutated data is passed through a "behavior processor" which applies any final, deterministic transformations, such as updating a sequence number or timestamp. This step is crucial for ensuring the message is still valid enough to be accepted by the target.
4.  **Queue for Execution**: The final test case is packaged and sent to the target, either directly or via an agent.

## The `MutationEngine`

The `MutationEngine` (`core/engine/mutators.py`) is the primary component responsible for altering seed data. It supports three main modes of operation, which can be configured for each fuzzing session:

-   `byte_level`: The default mode. It applies simple, fast, protocol-agnostic mutations directly to the raw bytes of the seed.
-   `structure_aware`: An intelligent mode that uses knowledge of the protocol's structure (from a plugin) to create valid, complex mutations.
-   `hybrid`: A combination of both `byte_level` and `structure_aware` modes. This is often the most effective mode, as it generates a mix of valid and malformed test cases.

The choice of which mutation strategy to use is determined by the session's `mutation_mode` and, in `hybrid` mode, the `structure_aware_weight` (a percentage from 0 to 100).

```python
# core/engine/mutators.py - Simplified Logic

class MutationEngine:
    def generate_test_case(self, base_seed: bytes) -> bytes:
        use_structure_aware = False
        if self.mutation_mode == "structure_aware":
            use_structure_aware = True
        elif self.mutation_mode == "hybrid":
            # Use weighted random choice
            if random.randint(1, 100) <= self.structure_aware_weight:
                use_structure_aware = True

        if use_structure_aware and self.structure_mutator:
            return self.structure_mutator.mutate(base_seed)
        else:
            # Fallback to byte-level mutations
            mutator = random.choice(self.byte_mutators)
            return mutator.mutate(base_seed)
```

## Byte-Level Mutations

Byte-level mutators are simple, fast, and effective at finding shallow bugs. They operate directly on the raw bytes of a seed without any understanding of the underlying protocol structure. This makes them great for finding parsing errors and other low-level vulnerabilities.

The primary byte-level mutators are implemented in `core/engine/mutators.py`:

-   **`BitFlipMutator`**: Flips a small number of random bits in the data. A `flip_ratio` (default: 1%) determines how many bits are flipped relative to the total number of bits. This is a very subtle mutation, effective for corrupting data in ways that might bypass simple checks.

-   **`ByteFlipMutator`**: Replaces a small number of random bytes with entirely new random values (0-255). The `flip_ratio` (default: 5%) controls the percentage of bytes to be replaced. This is a more destructive mutation than a bit flip.

-   **`ArithmeticMutator`**: This mutator treats a random 4-byte chunk of the data as a 32-bit integer and performs a simple arithmetic operation on it (adding or subtracting a small value). This is highly effective for corrupting numerical fields like counters, lengths, or identifiers in a way that might trigger overflow, underflow, or logic errors.

-   **`InterestingValueMutator`**: Overwrites a random part of the data (1, 2, or 4 bytes) with "interesting" values known to cause edge cases in software. These include values like `0`, `-1`, `MAX_INT`, `MIN_INT`, and powers of two.

-   **`HavocMutator`**: This is the most aggressive byte-level mutator. In a single call, it applies a sequence of 2 to 10 random, destructive actions, such as:
    -   **Insert**: Inserts a small chunk of random bytes.
    -   **Delete**: Deletes a small chunk of bytes.
    -   **Duplicate**: Duplicates a chunk of the data and inserts it elsewhere.
    -   **Shuffle**: Shuffles the bytes within a small, randomly selected chunk.
    This mutator is excellent for drastically changing the structure and size of the input data, which can uncover buffer overflows and other memory corruption vulnerabilities.

-   **`SpliceMutator`**: This mutator combines two different seeds from the corpus. It takes a random portion from the beginning of one seed and appends a random portion from the end of a second seed. This can be effective at discovering how a target handles unexpected combinations of valid inputs.

## Structure-Aware Mutations

Structure-aware mutation is the most powerful and intelligent feature of the fuzzing engine. It allows the fuzzer to generate complex, valid test cases that can penetrate deep into an application's logic. This is handled by the `StructureAwareMutator` (`core/engine/structure_mutators.py`).

The process relies entirely on the `data_model` provided by a protocol plugin and consists of four main steps:

1.  **Parse**: The raw bytes of a seed are passed to the `ProtocolParser`, which uses the `data_model` to deconstruct the message into a structured dictionary of fields and their values.
2.  **Select Field**: The mutator identifies all fields in the `data_model` that are marked as `mutable: True`. It then randomly selects one of these fields to mutate. This ensures that critical, static fields like magic headers are not changed.
3.  **Mutate Field Value**: A mutation strategy is applied to the value of the chosen field. These strategies are type-aware. For example, if the field is an integer, an arithmetic mutation might be applied. If it's a byte array, its content might be changed or its length altered.
4.  **Serialize**: The modified dictionary of fields is passed back to the `ProtocolParser`. The parser serializes it back into a raw byte string. During this step, it automatically recalculates any dependent fields, such as length prefixes or checksums (if configured).

This process ensures that the resulting test case is still structurally valid according to the protocol's rules, even after mutation. This allows it to bypass the target's initial parsing and validation checks and test the deeper, more complex application logic that lies behind them.

```python
# core/engine/structure_mutators.py - Simplified Logic

class StructureAwareMutator:
    def mutate(self, seed: bytes) -> bytes:
        # 1. Parse message into structured fields
        fields = self.parser.parse(seed)

        # 2. Select a mutable field to mutate
        mutable_fields = self._get_mutable_fields()
        target_block = random.choice(mutable_fields)
        field_name = target_block['name']

        # 3. Select and apply a type-aware mutation strategy
        original_value = fields[field_name]
        mutated_value = self._apply_strategy(strategy, original_value, target_block)
        fields[field_name] = mutated_value

        # 4. Serialize back to bytes, with auto-fixing of lengths/checksums
        return self.parser.serialize(fields)
```

The combination of simple, fast byte-level mutations and intelligent, complex structure-aware mutations allows the fuzzer to generate a highly diverse range of test cases, maximizing its chances of discovering vulnerabilities at all levels of the target application.