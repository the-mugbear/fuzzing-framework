# 4. Corpus and Crash Triage

**Last Updated: 2025-11-25**

Beyond the core fuzzing loop, the engine has two critical subsystems that support its operation: the **Corpus Store** for managing test cases and the **Crash Triage** process for saving and analyzing findings.

## Corpus Management

The "corpus" is the collection of all test cases that the fuzzer uses as input for mutation. A high-quality corpus is essential for a successful fuzzing campaign. The `CorpusStore` (`core/corpus/store.py`) is the component responsible for managing this data.

The corpus consists of two main types of data:

1.  **Seeds**: The initial inputs for the fuzzer. These are typically a small set of valid messages provided by a protocol plugin or uploaded by the user.
2.  **Findings**: Crash-inducing test cases that are discovered during a fuzzing session.

### The `CorpusStore`

The `CorpusStore` provides a simple, file-system-based approach to managing the corpus. It maintains a `seeds` directory for the initial seeds and a `findings` directory for crashes.

-   **Adding Seeds**: When a new seed is added, the store calculates a SHA256 hash of its content and uses it as the `seed_id` to avoid duplicates. The raw seed data is saved to `data/corpus/seeds/` and also kept in an in-memory cache for fast access during the fuzzing loop.
-   **Retrieving Seeds**: During the fuzzing loop, the engine retrieves seed data from the store's in-memory cache.

## Crash Triage

When a test case causes a crash, hang, or other anomalous behavior in the target, it is considered a "finding." The process of saving, analyzing, and bucketing these findings is known as crash triage.

### Detecting a Crash

A crash is detected when the connection to the target is unexpectedly lost, or when the target fails to respond within a timeout period. When the `FuzzOrchestrator` (or an agent) observes this, it flags the test case as a potential finding.

### Saving a Finding

The `FuzzOrchestrator` reports the finding to the `CrashReporter` (`core/engine/crash_handler.py`), which then instructs the `CorpusStore` to save it. The `save_finding` method in the `CorpusStore` performs these key actions:

1.  **Saves the Input**: The raw bytes of the test case that caused the crash are saved to a file named `input.bin` inside a new directory under `data/crashes/`. The directory is named with a unique UUID for the finding.
2.  **Saves the Response**: If the target sent any data back before the connection was lost, that data is saved to `response.bin`.
3.  **Saves the Report**: A detailed report is saved in two formats: `report.json` (human-readable) and `report.msgpack` (a more compact binary format).

The report contains critical metadata about the crash, including the session ID, the exact time the crash occurred, the type of finding (e.g., `CRASH`, `HANG`), and any telemetry from the agent at the time of the crash.

### Future: Crash Bucketing

Currently, every unique crash-inducing input is saved as a new finding. A planned improvement for the triage system is **crash bucketing**. This involves analyzing crashes to determine if they are duplicates of an existing finding (e.g., by comparing stack traces), which would reduce the amount of manual analysis required by the user.
