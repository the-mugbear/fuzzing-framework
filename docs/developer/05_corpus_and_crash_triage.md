# 5. Corpus and Crash Triage

Beyond the core fuzzing loop, the engine has two critical subsystems that support its operation: the **Corpus Store** for managing test cases and the **Crash Triage** process for saving and analyzing findings.

## Corpus Management

The "corpus" is the collection of all test cases that the fuzzer uses as input for mutation. A high-quality corpus is essential for a successful fuzzing campaign. The `CorpusStore` (`core/corpus/store.py`) is the component responsible for managing this data.

The corpus consists of two main types of data:

1.  **Seeds**: The initial inputs for the fuzzer. These are typically a small set of valid messages provided by a protocol plugin or uploaded by the user.
2.  **Findings**: Crash-inducing test cases that are discovered during a fuzzing session. These are automatically added to the corpus to be used as seeds in future sessions, a process often called "feedback-driven fuzzing."

### The `CorpusStore`

The `CorpusStore` provides a simple, file-system-based approach to managing the corpus.

-   **Adding Seeds**: When a fuzzing session is created, the `FuzzOrchestrator` loads the seeds from the protocol plugin and adds them to the corpus store using the `add_seed` method. To avoid duplication, the store calculates a SHA256 hash of the seed's content and uses it as the `seed_id`. If a seed with the same hash already exists, it is ignored. The raw seed data is saved to `data/corpus/seeds/` and also kept in an in-memory cache for fast access during the fuzzing loop.

-   **Retrieving Seeds**: During the fuzzing loop, the engine retrieves seed data from the store's in-memory cache (`_seed_cache`) by its ID. This is much faster than reading from the disk in every iteration.

```python
# core/corpus/store.py - Simplified Logic

class CorpusStore:
    def add_seed(self, data: bytes) -> str:
        """Add a new seed to the corpus, avoiding duplicates."""
        seed_id = hashlib.sha256(data).hexdigest()

        if seed_id in self._seed_cache:
            return seed_id  # Already exists

        # Write seed file to disk
        seed_path = self.seeds_dir / f"{seed_id}.bin"
        seed_path.write_bytes(data)

        # Add to in-memory cache
        self._seed_cache[seed_id] = data
        return seed_id

    def get_seed(self, seed_id: str) -> Optional[bytes]:
        """Retrieve a seed by its ID from the cache."""
        return self._seed_cache.get(seed_id)
```

## Crash Triage

When a test case causes a crash, hang, or other anomalous behavior in the target, it is considered a "finding." The process of saving, analyzing, and bucketing these findings is known as crash triage.

### Detecting a Crash

A crash is detected when the connection to the target is unexpectedly lost. This could be a TCP RST packet, a closed socket, or a failure to respond within a timeout period. When the `FuzzOrchestrator` (or an agent) observes this, it flags the test case that was just sent as a potential finding.

### Saving a Finding

The `FuzzOrchestrator` reports the finding to the `CrashReporter` (`core/engine/crash_handler.py`), which then instructs the `CorpusStore` to save it. The `save_finding` method in the `CorpusStore` performs two key actions:

1.  **Saves the Input**: The raw bytes of the test case that caused the crash are saved to a file named `input.bin` inside a new directory under `data/crashes/`. The directory is named with a unique UUID for the finding.
2.  **Saves the Report**: A detailed report is saved alongside the input. This report is stored in two formats: `report.json` (human-readable) and `report.msgpack` (a more compact binary format).

The report contains critical metadata about the crash, including:
-   The session ID.
-   The exact time the crash occurred.
-   The type of finding (e.g., `CRASH`, `HANG`).
-   Any error messages.
-   Telemetry from the agent at the time of the crash (e.g., CPU and memory usage).

This ensures that every crash is fully documented and reproducible. The `input.bin` file can be used with the "one-off execution" endpoint to easily verify that the crash is deterministic.

### Future: Crash Bucketing

Currently, every unique crash-inducing input is saved as a new finding. A planned improvement for the triage system is **crash bucketing**. This involves analyzing crashes to determine if they are duplicates of an existing finding.

For example, two slightly different test cases might trigger the same underlying bug and result in crashes with very similar stack traces. A crash bucketing system would analyze the stack trace (or other crash data) and group these two crashes into the same "bucket," reducing the amount of manual analysis required by the user. This would involve extending the `CrashReporter` to generate a "crash signature" and checking for that signature before saving a new finding.