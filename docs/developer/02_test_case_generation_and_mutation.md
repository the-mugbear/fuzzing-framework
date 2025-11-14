# Fuzzing Engine: Developer Documentation

## 2. Test Case Generation and Mutation

Test cases are the lifeblood of the fuzzer. The engine does not generate them from scratch; instead, it uses a process of **selection** and **mutation**. This approach allows the fuzzer to explore the target's state space by making incremental changes to known-good inputs.

The process is managed by the `FuzzOrchestrator` and the `MutationEngine`.

### The Fuzzing Loop

The core logic resides in the `_run_fuzzing_loop` method of the `FuzzOrchestrator`. In each iteration, it performs the following steps to generate a single test case:

1.  **Select a Base Seed**: A seed is chosen from the initial corpus. In a simple stateless fuzzing session, this is a round-robin selection. In a stateful session, a seed is intelligently chosen to match the protocol's current state.
2.  **Mutate the Seed**: The chosen seed is passed to the `MutationEngine`, which applies one or more mutation strategies to create a new, unique test case.
3.  **Apply Behaviors**: The mutated data is passed through a "behavior processor," which can apply final transformations, such as updating a sequence number or timestamp.
4.  **Execute**: The final test case is sent to the target.

Here is a simplified view of the seed selection and mutation logic in `core/engine/orchestrator.py`:

```python
# core/engine/orchestrator.py

class FuzzOrchestrator:
    # ...
    async def _run_fuzzing_loop(self, session_id: str):
        # ...
        while session.status == FuzzSessionStatus.RUNNING:
            # ...
            # Stateless fuzzing: random seed selection (existing behavior)
            base_seed = seeds[iteration % len(seeds)]

            # Mutate the selected seed
            test_case_data = mutation_engine.generate_test_case(base_seed)
            final_data = self._apply_behaviors(session, test_case_data)

            test_case = TestCase(
                id=str(uuid.uuid4()),
                session_id=session_id,
                data=final_data,
                # ...
            )

            # Execute test case
            # ...
```

### The Mutation Engine

The `MutationEngine` (`core/engine/mutators.py`) is the component responsible for altering seed data. It supports three primary modes of operation, configured per session:

-   `byte_level`: The default mode. Applies simple, protocol-agnostic mutations.
-   `structure_aware`: An intelligent mode that uses protocol knowledge to create valid, complex mutations.
-   `hybrid`: A mix of both, allowing for both valid and malformed test cases.

The choice of which mutation strategy to use is determined by the session's `mutation_mode` and the `structure_aware_weight`.

```python
# core/engine/mutators.py

class MutationEngine:
    # ...
    def generate_test_case(self, base_seed: bytes, num_mutations: int = 1) -> bytes:
        # ...
        use_structure_aware = False

        if self.mutation_mode == "structure_aware":
            use_structure_aware = self.structure_mutator is not None
        elif self.mutation_mode == "hybrid" and self.structure_mutator is not None:
            # Weighted random choice
            use_structure_aware = random.randint(1, 100) <= self.structure_aware_weight

        # Apply mutations
        if use_structure_aware:
            # Structure-aware mutation
            return self.structure_mutator.mutate(base_seed)
        else:
            # Byte-level mutation (original behavior)
            # ...
```

### Byte-Level Mutations

These are simple, fast, and effective at finding shallow bugs. They operate directly on the raw bytes of a seed without any understanding of the underlying protocol. The `MutationEngine` selects from a pool of available byte-level mutators based on a weighted random choice.

Here are the primary byte-level mutators implemented in `core/engine/mutators.py`:

-   **`BitFlipMutator`**: Flips random bits in the data. A `flip_ratio` (default: 1%) determines how many bits are flipped relative to the total number of bits in the data. This is effective for corrupting data in subtle ways.

    ```python
    # core/engine/mutators.py - BitFlipMutator
    def mutate(self, data: bytes) -> bytes:
        data_array = bytearray(data)
        num_bits = len(data) * 8
        num_flips = max(1, int(num_bits * self.flip_ratio))

        for _ in range(num_flips):
            bit_pos = random.randint(0, num_bits - 1)
            byte_pos = bit_pos // 8
            bit_offset = bit_pos % 8
            data_array[byte_pos] ^= 1 << bit_offset
    ```

-   **`ByteFlipMutator`**: Replaces random bytes with entirely new random values (0-255). The `flip_ratio` (default: 5%) controls the percentage of bytes to be replaced. This is a more destructive mutation than a bit flip.

-   **`ArithmeticMutator`**: This mutator treats a random 4-byte chunk of the data as a 32-bit integer and adds or subtracts a small value (e.g., -1, 8, 128). This is useful for corrupting numerical fields like counters, lengths, or identifiers in a way that might trigger overflow or underflow conditions.

-   **`InterestingValueMutator`**: Overwrites a random part of the data with "interesting" values known to cause edge cases in software. These include values like `0`, `-1`, `MAX_INT`, and powers of two. The mutator randomly chooses to overwrite 1, 2, or 4 bytes.

    ```python
    # core/engine/mutators.py - InterestingValueMutator
    INTERESTING_32 = [0, 1, 65535, 65536, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]
    ```

-   **`HavocMutator`**: Applies a sequence of aggressive, random mutations to the data. In a single `mutate` call, it can perform 2 to 10 of the following actions, chosen randomly:
    -   **Insert**: Inserts a small chunk of random bytes.
    -   **Delete**: Deletes a small chunk of bytes.
    -   **Duplicate**: Duplicates a chunk of the data and inserts it elsewhere.
    -   **Shuffle**: Shuffles the bytes within a small, randomly selected chunk.
    This mutator is excellent for drastically changing the structure and size of the input data.

-   **`SpliceMutator`**: This mutator combines two different seeds from the corpus. It takes a random portion from the beginning of the first seed and appends a random portion from the end of the second seed, creating a new hybrid test case. This can be effective at discovering how a target handles unexpected combinations of valid inputs.

### Structure-Aware Mutations

This is the most powerful feature of the fuzzing engine. The `StructureAwareMutator` (`core/engine/structure_mutators.py`) uses the `data_model` provided by a protocol plugin to perform "intelligent" mutations.

The process is as follows:

1.  **Parse**: The raw bytes of the seed are parsed into a structured dictionary of fields, according to the `data_model`.
2.  **Select Field**: A random field marked as `mutable` in the `data_model` is chosen.
3.  **Mutate Field**: A mutation strategy is applied to the value of the chosen field. These strategies are type-aware (e.g., applying arithmetic to integers, changing the length of byte arrays).
4.  **Serialize**: The modified dictionary of fields is serialized back into raw bytes. During this step, the `ProtocolParser` automatically recalculates any dependent fields, such as length prefixes or checksums, ensuring the resulting test case is still valid according to the protocol's rules.

This allows the fuzzer to explore deep application logic that requires structurally valid messages.

```python
# core/engine/structure_mutators.py

class StructureAwareMutator:
    # ...
    def mutate(self, seed: bytes) -> bytes:
        # 1. Parse message into structured fields
        fields = self.parser.parse(seed)

        # 2. Select a mutable field to mutate
        mutable_fields = self._get_mutable_fields()
        # ...
        target_block = random.choice(mutable_fields)
        field_name = target_block['name']

        # 3. Select and apply mutation strategy
        strategy = random.choice(self.strategy_list)
        original_value = fields[field_name]
        mutated_value = self._apply_strategy(
            strategy,
            original_value,
            target_block
        )
        fields[field_name] = mutated_value

        # 4. Serialize back to bytes (auto-fixes lengths, checksums)
        return self.parser.serialize(fields)
```

The combination of these mutation strategies allows the fuzzer to generate a diverse range of test cases, from slightly corrupted but valid messages to completely malformed random data.
