# 4. Corpus, Crashes, and History

**Last Updated: 2026-01-26**

The fuzzer relies on three key types of data: the **corpus** of inputs, **crashes** (or "findings"), and the complete **execution history** of a session. Each is handled by a specialized component.

## 1. Corpus Management (`core/corpus/store.py`)

The "corpus" is the collection of all test cases that the fuzzer uses as a starting point for mutation. A high-quality corpus is essential for a successful fuzzing campaign. The `CorpusStore` is the component responsible for managing this data.

The corpus consists of two main types of data:
1.  **Seeds**: The initial inputs for the fuzzer, provided by a plugin or user.
2.  **Findings**: Crash-inducing test cases that are discovered during a session and are deemed worthy of being added to the corpus for future fuzzing runs.

### The `CorpusStore`

The `CorpusStore` uses a simple, file-system-based approach, storing all corpus files in the `data/corpus/` directory.

-   **Adding to Corpus**: When a new item is added, the store calculates a SHA256 hash of its content to use as a unique ID, preventing duplicates. The raw data is saved to `data/corpus/` and also kept in an in-memory cache for fast access during the fuzzing loop.
-   **Retrieving Inputs**: During the fuzzing loop, the engine retrieves seed data from the store's in-memory cache for performance.

## 2. Crash Triage (`core/engine/crash_handler.py`)

When a test case causes a crash, hang, or other anomalous behavior, it is considered a "finding." The process of saving and analyzing these findings is known as crash triage.

### Detecting a Crash

A crash is detected when the connection to the target is unexpectedly lost or when the target fails to respond within a timeout period. When this occurs, the `FuzzOrchestrator` (or an agent) flags the test case as a potential finding.

### The `CrashReporter`

The `FuzzOrchestrator` reports the finding to the `CrashReporter`, which is responsible for persisting it. It performs these key actions:

1.  **Creates a Finding Directory**: It creates a new directory under `data/crashes/` with a unique UUID for the finding.
2.  **Saves the Input**: The raw bytes of the test case that caused the crash are saved to a file named `input.bin`.
3.  **Saves the Response**: If the target sent any data back before crashing, that data is saved to `response.bin`.
4.  **Saves Metadata**: A detailed report is saved as `report.json`, containing critical metadata like the session ID, the exact time of the crash, the type of finding (e.g., `CRASH`, `HANG`), and agent telemetry.

### Future: Crash Bucketing

Currently, every unique crash-inducing input is saved as a new finding. A planned improvement is **crash bucketing**: analyzing crashes to determine if they are duplicates of an existing finding (e.g., by comparing stack traces), which would reduce manual analysis for the user.

## 3. Execution History (`core/engine/history_store.py`)

The `ExecutionHistoryStore` is a critical component for performance and post-session analysis. It records every single test case that is generated and sent to the target.

This store uses a hybrid approach for performance:
-   **SQLite Backend**: All execution records are saved to a SQLite database located at `data/correlation.db`. An asynchronous, batched writer is used to ensure that database writes do not block the main fuzzing loop.
-   **In-Memory Cache**: A small in-memory cache holds the most recent execution records. This allows the Web UI to feel responsive, displaying recent test cases instantly without needing to query the database.

The detailed execution history is essential for:
-   Visualizing the fuzzing process in the UI.
-   Debugging protocol plugins by replaying a sequence of messages.
-   Correlating fuzzer activity with target behavior over time.
