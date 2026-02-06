# 4. Data Management: Corpus, Crashes, and History

**Last Updated: 2026-02-06**

The fuzzer relies on three key types of data: the **corpus** of inputs, **crashes** (or "findings"), and the complete **execution history** of a session. Each is handled by a specialized component.

## 1. Corpus Management (`core/corpus/store.py`)

The "corpus" is the collection of all test cases that the fuzzer uses as a starting point for mutation. The `CorpusStore` is the component responsible for managing this data, which consists of initial seeds from plugins and new findings that are added back into the corpus.

### The `CorpusStore`

The `CorpusStore` uses a simple, file-system-based approach, storing all corpus files in the `data/corpus/` directory.

-   **Adding to Corpus**: When a new item is added, the store calculates a SHA256 hash of its content to use as a unique ID, preventing duplicates.
-   **Retrieving Inputs**: During the fuzzing loop, the engine retrieves seed data from the store's in-memory cache for performance.

### Data Management in Orchestrated Sessions

In an **Orchestrated Session**, the concept of a corpus remains the same, but its application is stage-specific.

-   Each stage in a `protocol_stack` is defined by its own plugin (`bootstrap`, `fuzz_target`, etc.).
-   When the fuzzer needs to select a seed for a particular stage, it **only considers the seeds defined in that stage's plugin**.
-   This provides a clean separation of concerns, allowing you to have a set of handshake-specific seeds for your `bootstrap` stage and a completely different set of application-level seeds for your `fuzz_target` stage.

## 2. Crash Triage (`core/engine/crash_handler.py`)

When a test case causes a crash, hang, or other anomalous behavior, it is considered a "finding." The `CrashReporter` component is responsible for saving and analyzing these findings.

### Detecting a Crash
A crash is typically detected when the connection to the target is unexpectedly lost or when the target fails to respond within a timeout period.

### The `CrashReporter`
The `FuzzOrchestrator` reports the finding to the `CrashReporter`, which persists it:

1.  **Creates a Finding Directory**: A new directory is created under `data/crashes/` with a unique UUID.
2.  **Saves the Input**: The raw bytes of the test case are saved to `input.bin`.
3.  **Saves Metadata**: A detailed report is saved as `report.json`.

### Crash Reporting in Orchestrated Sessions
For an orchestrated session, the crash report is augmented with crucial context:

-   The `report.json` will contain a **`stage`** field, indicating in which stage of the `protocol_stack` the crash occurred (e.g., `"stage": "fuzz_target"`).
-   This is critical for debugging, as a crash in the `bootstrap` stage points to a problem with the handshake, while a crash in the `fuzz_target` stage points to a bug in the application logic.

## 3. Execution History (`core/engine/history_store.py`)

The `ExecutionHistoryStore` records every single test case that is generated and sent to the target. This provides a complete, auditable trail of the fuzzing session.

### Architecture

The store uses a hybrid approach for high performance:

-   **SQLite Backend**: All execution records are saved to a SQLite database at `data/correlation.db`. An asynchronous, batched writer processes records in the background to avoid blocking the main fuzzing loop.
-   **In-Memory Cache**: A circular buffer (default: 100 records) holds the most recent records for real-time UI updates.
-   **Sequence Counters**: Track the highest sequence number per session for accurate pagination.

### Key Operations

| Method | Description |
| ------ | ----------- |
| `record()` | Records a test execution, adding to cache and queue for async write |
| `list()` | Retrieves records with SQLite + cache merge for consistency |
| `total_count()` | Returns accurate count using sequence counters |
| `flush()` | Synchronously writes all pending records (called on session stop) |
| `find_by_sequence()` | Fast lookup by sequence number (primary key) |
| `find_at_time()` | Find record at a specific timestamp |

### Pagination Strategy

The `list()` method uses a merge strategy to handle the gap between cache and SQLite:

1. **First page (offset=0)**: Query SQLite, then merge in any cache records not yet written
2. **Subsequent pages (offset>0)**: Query SQLite directly (older records are always persisted)

This ensures users see the most recent records even if the background writer is behind, while pagination works correctly for historical data.

### Data Serialization

Records containing `context_snapshot` or `parsed_fields` may include bytes values. The store uses a `_json_safe()` helper to convert bytes to base64 before JSON serialization, preventing serialization errors.

### Execution History in Orchestrated Sessions

The history store transparently handles orchestrated sessions by recording test cases from **all stages**. Each record includes:

-   `stage_name`: Which stage produced the record (e.g., "bootstrap", "fuzz_target")
-   `context_snapshot`: Protocol context at execution time (for replay)
-   `parsed_fields`: Parsed field values for re-serialization
-   `connection_sequence`: Position within the current connection

When viewing execution history for an orchestrated session, you see the complete sequence of messages including the `bootstrap` handshake, fuzzed messages from `fuzz_target`, and any `teardown` messages. This enables complete end-to-end replay of interactions that led to findings.