# Orchestrated Sessions Architecture - Implemented

## Document Information

| Field | Value |
|-------|-------|
| Status | Implemented |
| Created | 2026-01-29 |
| Last Updated | 2026-01-30 |

---

## Overview

This document describes the implemented architecture for orchestrated sessions – a fundamental enhancement enabling multi-protocol fuzzing with shared context, persistent connections, and scheduled heartbeats.

### Problem Solved

The previous architecture bound fuzzing sessions to a single protocol plugin with per-test TCP connections. This limited the fuzzer's ability to test modern protocols that require:

1.  **Bootstrap handshakes**: Initial exchanges to obtain tokens/keys for subsequent messages.
2.  **Persistent connections**: Long-lived sockets with keep-alive requirements.
3.  **Shared context**: Values extracted from one protocol stage (e.g., login) and used in another (e.g., core fuzzing).
4.  **Reliable replay**: Reproducing issues that depend on session state.

### Goals Achieved

-   Support multi-stage protocol sessions defined in plugins.
-   Enable response-derived values to flow between stages via session context.
-   Support persistent connections with scheduled heartbeats.
-   Make replay reliable by rebuilding session state or using stored context.

### Current Limitations

-   **User-assembled protocol stacks in UI**: Protocol stacks are defined by plugin authors, not directly configurable by users in the UI.
-   **Dynamic stage switching**: Stages execute in a predefined, linear order.
-   **Context value expiration/TTL**: Context values do not expire automatically. For protocols with time-limited tokens, plugin authors must configure connection lifecycle settings (e.g., `on_drop.rebootstrap`) to trigger re-bootstrap when needed.
-   **Multi-target sessions**: A session is still bound to a single `host:port` target.

---

## Core Concepts

### ProtocolContext (`core/engine/protocol_context.py`)

A session-scoped key-value store. It acts as the "shared memory" between different stages of an orchestrated session. Values are:
-   **Populated**: During bootstrap stages via `exports` definitions in the plugin.
-   **Injected**: Into outgoing messages via the `from_context` field attribute in the `data_model`.
-   **Persisted**: The context is snapshotted and stored with the session and each execution record for resume and replay capabilities.

### Protocol Stack

An ordered sequence of protocol stages defined in a plugin using the `protocol_stack` attribute. Each stage:
-   Is defined by a name, a role (`bootstrap`, `fuzz_target`, or `teardown`), and a plugin (or inline `data_model`).
-   Executes in a predefined order. Bootstrap stages run once per connection establishment. The `fuzz_target` stage runs the main mutation loop.

**Bootstrap Stage Policies:**

| Aspect | Policy |
|--------|--------|
| **Fuzzing** | Bootstrap stages are **not** fuzzed. They use `data_model` defaults to ensure reliable context extraction. |
| **Recording** | Bootstrap executions **are** recorded in history with `stage_name="bootstrap"`. |
| **Seeds** | Bootstrap stages do not use seeds. The `seeds` list in a plugin applies only to `fuzz_target` stages. |
| **Retry** | Bootstrap failures trigger retries based on the `retry` config within the stage definition. After max retries, the session fails with a clear error. |

### ConnectionManager (`core/engine/connection_manager.py`)

Manages the lifecycle of network transports (connections) across stages. It wraps the existing `Transport` abstraction to support:
-   **Persistent Connections**: Keeps a single connection open across multiple test cases or stages.
-   **Send Coordination**: Uses an `asyncio.Lock` to serialize all `send()` operations, preventing race conditions when both the fuzzing loop and the heartbeat are trying to send data on the same socket.
-   **Health Tracking**: Monitors the connection status and can trigger reconnections.

Supports three connection modes configured via the plugin's `connection.mode` attribute:

| Mode | Behavior | Lifecycle | Use Case |
|------|----------|-----------|----------|
| `per_test` | New connection for each test case | Open → send → receive → close | Stateless protocols (traditional behavior) |
| `per_stage` | Connection persists within a single stage | Open at stage start → close on stage complete/fail | Stage isolation (rarely used in practice) |
| `session` | Single connection across all stages | Open once → persist across all stages → close on session end | Stateful protocols with persistent sessions (most common for orchestration) |

### HeartbeatScheduler (`core/engine/heartbeat_scheduler.py`)

Sends periodic keep-alive messages on persistent connections. Key behaviors:
-   Runs concurrently with the fuzzing loop as an `asyncio` task.
-   Coordinates sends via the `ConnectionManager`'s mutex to prevent message interleaving.
-   Detects failures and triggers reconnection if configured via `on_timeout`.
-   Supports jitter (`jitter_ms`) to avoid predictable patterns.
-   Heartbeat messages can be dynamically constructed using values from the `ProtocolContext` (`from_context`).

### Response Demultiplexing Strategy

When heartbeat and fuzz traffic share a connection, responses can arrive out-of-order or unsolicited. The architecture uses **strict serialization with a single-reader dispatch**:
1.  **Single owner**: The `ManagedTransport` (managed by `ConnectionManager`) owns the socket and runs a single `_reader_loop` task.
2.  **Send serialization**: All sends (fuzz, heartbeat, bootstrap) acquire a mutex (`send_with_lock`) before writing to the socket.
3.  **Response dispatch**: Incoming data is processed by the `_reader_loop` and dispatched:
    -   To the `await`ing request (e.g., the fuzzing loop or the heartbeat).
    -   Unsolicited responses can be queued, ignored, or logged based on `demux.unsolicited_handler` configuration.

**Message Correlation Options** (plugin-configurable via `connection.demux.strategy`):

| Strategy | When to Use |
|----------|-------------|
| **`sequential`** (Default) | Protocol guarantees request-response ordering (responses are matched to the oldest pending request). |
| **`tagged`** | Protocol has a request ID field (response ID is matched to a pending request ID using `correlation_field`). |
| **`type_based`** | Responses have distinct types (response type is matched to an expected type, useful for heartbeats). |

### Context Snapshot Policy

`ProtocolContext` values are stored with the session and with each `TestCaseExecutionRecord`.
-   Only keys explicitly referenced by `exports` or `export_to_context` are included in snapshots.
-   Binary values (bytes) are hex-encoded for JSON serialization.
-   Snapshots are truncated at 64KB with a warning if exceeded, to prevent excessive database growth.
-   Context values are stored in the session database (SQLite) and are **not encrypted**.

---

## Plugin Schema

### Single-Stage Plugin (Backward Compatible)

Existing plugins continue to work unchanged. When no `protocol_stack` is defined, the framework implicitly wraps the plugin in a single-stage stack with `role: "fuzz_target"`.

```python
# simple_proto.py (example of implicit single-stage)

__version__ = "1.0.0"

data_model = {
    "name": "SimpleProto",
    "blocks": [...]
}

state_model = {
    "initial_state": "READY",
    "states": ["READY", "DONE"],
    "transitions": [...]
}
```

### Multi-Stage Plugin (`protocol_stack`)

The `protocol_stack` attribute defines an orchestrated session. It is a list of stage definitions.

```python
# secure_application.py

__version__ = "1.0.0"

protocol_stack = [
    {
        "name": "handshake",
        "role": "bootstrap",
        "data_model": {...},            # Request message structure for handshake
        "response_model": {...},        # Response message structure for parsing
        "exports": {                    # Extract values from response into ProtocolContext
            "session_token_field": "auth_token",
            "server_nonce_field": "nonce"
        },
        "expect": {"status": 0x00},     # Validation - bootstrap fails if response doesn't match
        "retry": {                      # Retry config for transient failures
            "max_attempts": 3,
            "backoff_ms": 1000
        }
    },
    {
        "name": "application",
        "role": "fuzz_target",
        "data_model": {
            "blocks": [
                {"name": "token", "type": "uint64", "from_context": "auth_token", "mutable": False},
                {"name": "command", "type": "uint8", "values": {...}},
                {"name": "payload", "type": "bytes", "max_size": 4096},
            ]
        },
        "response_model": {...},
        "state_model": {                # Optional: state machine for this fuzz_target stage
            "initial_state": "READY",
            "states": ["READY", "PROCESSING"],
            "transitions": [...]
        },
        "response_handlers": [          # Optional: Update context during fuzzing based on responses
            {"name": "track_server_sequence", "match": {"status": 0x00}, "export_to_context": {"last_sequence": "sequence_num"}}
        ]
    }
]

connection = {
    "mode": "session",              # "per_test", "per_stage", or "session"
    "on_drop": {                    # What to do when connection drops unexpectedly
        "action": "reconnect",      # "reconnect" or "abort"
        "rebootstrap": True,        # Re-run bootstrap stages on reconnect
        "max_reconnects": 5,
        "backoff_ms": 1000
    },
    "on_error": {                   # What to do on send/receive errors
        "action": "reconnect",
        "backoff_ms": 1000
    },
    "demux": {
        "strategy": "sequential",       # "sequential", "tagged", "type_based"
        "correlation_field": "request_id", # For "tagged" strategy
        "unsolicited_handler": "log",   # "log", "queue", "ignore"
    },
    "context_snapshot": {           # Control context snapshotting
        "enabled": True,
        "exclude_keys": ["sensitive_token"]
    }
}

heartbeat = {
    "enabled": True,
    "interval_ms": 30000,               # Fixed value, or dynamic from context {"from_context": "hb_interval"}
    "jitter_ms": 5000,
    "message": {
        "data_model": {
            "blocks": [
                {"name": "magic", "type": "bytes", "size": 4, "default": b"BEAT"},
                {"name": "token", "type": "uint64", "from_context": "auth_token", "mutable": False},
                {"name": "timestamp", "type": "uint32", "generate": "unix_timestamp"}
            ]
        }
    },
    "expect_response": True,
    "response_timeout_ms": 5000,
    "on_timeout": {                     # What to do on heartbeat failure
        "action": "reconnect",          # "reconnect", "abort", or "warn"
        "max_failures": 3,
        "rebootstrap": True             # Re-run bootstrap if reconnecting
    }
}

seeds = [
    # Seeds for the fuzz target stage. Bootstrap stages use data_model defaults.
    b"APPM...",
]
```

### Field Attributes Reference (Implemented)

| Attribute | Type | Description |
|-----------|------|-------------|
| `from_context` | string | Context key to inject at serialization time. |
| `mutable` | bool | If `false`, the mutation engine skips this field (default: `true`). |
| `transform` | list | Operations applied to context value before injection. |
| `generate` | string | Dynamic value generator: `unix_timestamp`, `random_bytes:N`, `sequence` (per-session counter). |
| `is_size_field` | bool | The field's value is the length of another field. |
| `is_checksum` | bool | The field's value is an auto-calculated checksum. |

### Export Syntax (Implemented)

**Simple mapping:**
```python
"exports": {"response_field_name": "context_key_name"}
```
**With transform:**
```python
"exports": {
    "response_field_name": {
        "as": "context_key_name",
        "transform": [{"operation": "add_constant", "value": 1}]
    }
}
```

---

## Data Models

### ProtocolContext (`core/engine/protocol_context.py`)

A runtime key-value store for session-scoped values.
```python
@dataclass
class ProtocolContext:
    values: Dict[str, Any] = field(default_factory=dict)
    bootstrap_complete: bool = False
    last_updated: Optional[datetime] = None
    # Includes get(), set(), clear(), snapshot(), restore() methods
```

### FuzzSession (Extended in `core/models.py`)

Extended with orchestration-specific fields.
```python
class FuzzSession(BaseModel):
    # ... existing fields ...
    protocol_stack_config: Optional[List[Dict]] = None
    current_stage: str = "default"
    context: Optional[Dict[str, Any]] = None # Persisted snapshot

    # Connection state
    connection_mode: Literal["per_test", "per_stage", "session"] = "per_test"
    reconnect_count: int = 0

    # Heartbeat state
    heartbeat_enabled: bool = False
    heartbeat_last_sent: Optional[datetime] = None
    heartbeat_last_ack: Optional[datetime] = None
    heartbeat_failures: int = 0
```

### TestCaseExecutionRecord (Extended in `core/models.py`)

Extended with orchestration context.
```python
class TestCaseExecutionRecord(BaseModel):
    # ... existing fields ...
    stage_name: Optional[str] = None
    context_snapshot: Optional[Dict[str, Any]] = None
    connection_sequence: int = 0
    parsed_fields: Optional[Dict[str, Any]] = None # For re-serialization in fresh replay
```

---

## Engine Architecture

### Component Diagram

```
+-------------------------------------------------------------------+
|                           FuzzOrchestrator                         |
|                                                                    |
|  +------------------+  +------------------+  +------------------+  |
|  |   StageRunner    |  |  ProtocolContext |  | ConnectionManager|  |
|  |                  |  |                  |  |                  |  |
|  | - runBootstrap() |  | - get()/set()    |  | - getConnection()|  |
|  | - runFuzzLoop()  |  | - snapshot()     |  | - sendWithLock() |  |
|  | - runTeardown()  |  | - restore()      |  | - reconnect()    |  |
|  +--------+---------+  +--------+---------+  +--------+---------+  |
|           |                     |                     |            |
|           +---------------------+---------------------+            |
|                                 |                                  |
|  +------------------------------+-------------------------------+  |
|  |                    HeartbeatScheduler                        |  |
|  |                                                              |  |
|  |  - start()/stop()                                            |  |
|  |  - heartbeatLoop() [async, coordinates via mutex]            |  |
|  |  - handleTimeout()                                           |  |
|  +--------------------------------------------------------------+  |
+-------------------------------------------------------------------+
                                  |
                                  v
                        +-------------------+
                        |      Target       |
                        +-------------------+
```

### Key Component Flows

#### `StageRunner` (`core/engine/stage_runner.py`)

Executes protocol stages. During `bootstrap`:
1.  Builds messages using `data_model` defaults (no fuzzing).
2.  Sends message via `ConnectionManager`.
3.  Parses response (if `response_model` defined).
4.  Validates response against `expect` criteria.
5.  **Exports** values from response to `ProtocolContext`.
6.  Handles retries on failure.

#### `ConnectionManager` (`core/engine/connection_manager.py`)

Manages `ManagedTransport` instances.
-   Provides `send_with_lock` for thread-safe writing to a persistent connection.
-   Handles `reconnect` logic, including optional `rebootstrap`.
-   Uses `TransportFactory` to create the underlying transport.

#### `HeartbeatScheduler` (`core/engine/heartbeat_scheduler.py`)

Runs a background `asyncio` loop for each session with an enabled heartbeat.
-   Calculates next send time (with `interval_ms` and `jitter_ms`).
-   Builds heartbeat message (can use `from_context` and `generate`).
-   Sends message via `ConnectionManager.send_with_lock`.
-   Monitors `expect_response` and `response_timeout_ms`.
-   On failure (e.g., timeout), logs a warning and, if `max_failures` is exceeded, triggers `on_timeout.action` (e.g., `reconnect` with `rebootstrap`).

#### `ProtocolParser` (`core/engine/protocol_parser.py`)

Updated to support `from_context`, `generate`, and `transform` during serialization.
-   Before actual serialization, it resolves values for fields:
    -   Priority: explicit value > `from_context` > `generate` > `default`.
    -   `from_context`: fetches value from `ProtocolContext`.
    -   `generate`: dynamically creates values (`unix_timestamp`, `random_bytes:N`, `sequence`).
    -   `transform`: applies operations (e.g., `add_constant`) to resolved values.

#### State Machine Integration

Each `fuzz_target` stage can define its own `state_model`. The `StatefulFuzzingSession` (`core/engine/stateful_fuzzer.py`) is instantiated and managed by the `FuzzOrchestrator` for that specific stage.
-   State tracking and exploration (modes: `random`, `breadth_first`, `depth_first`, `targeted`) operate *within the context of that `fuzz_target` stage*.
-   When a stage with a `state_model` is executed, it starts at its `initial_state`.
-   State is reset on stage transitions or reconnects.

---

## Replay Architecture

Replay allows reproducing a historical execution sequence. Orchestrated sessions introduce additional complexities to ensure replay fidelity.

### Replay Modes (API: `/api/sessions/{session_id}/execution/replay`)

| Mode | Behavior | Use Case |
|------|----------|----------|
| **`fresh`** (Default) | Re-runs bootstrap stages, establishes a new connection, and re-serializes messages using the new `ProtocolContext`. | Default for most scenarios. Ensures dynamic values (tokens, timestamps) are fresh. |
| **`stored`** | Replays exact historical raw bytes for each execution. Does *not* re-run bootstrap. | For protocols where tokens are long-lived or deterministic. Useful if bootstrap is complex/slow. |
| **`skip`** | No bootstrap is run, and messages are re-serialized with an empty context. | Manual testing or when the target is pre-configured and ready. |

### Replay Flow

1.  **Fetch History**: `ExecutionHistoryStore` retrieves records in *ascending* sequence order.
2.  **Setup Connection & Context**:
    -   **`fresh` mode**: A new connection is created. `StageRunner` re-executes `bootstrap` stages, populating a new `ProtocolContext`.
    -   **`stored` mode**: A new connection is created. The `ProtocolContext` is restored from the `context_snapshot` of the *first* replayed execution.
    -   **`skip` mode**: A new connection is created with an empty `ProtocolContext`.
3.  **Iterate Executions**: For each historical `TestCaseExecutionRecord`:
    -   **`stored` mode**: The `raw_payload_b64` is base64-decoded and sent directly.
    -   **`fresh`/`skip` modes**: The `parsed_fields` (stored in the history) are re-serialized using the *current* `ProtocolContext`. This ensures dynamic context values are up-to-date.
4.  **Record Result**: The outcome of each replayed message (success, timeout, error) is recorded.
5.  **Context Update**: If in `fresh` mode, any `response_handlers` in the `fuzz_target` plugin are applied to potentially update the `ProtocolContext` during replay.

### Key `ReplayExecutor` (`core/engine/replay_executor.py`) Responsibilities
-   Manages the connection and context for replay sessions.
-   Handles the different replay modes.
-   Ensures executions are processed in ascending order to correctly rebuild state.
-   Uses `parsed_fields` from history for accurate re-serialization in `fresh` and `skip` modes.

---

## API Changes (`core/api/routes/sessions.py`)

### New Endpoints and Data Models

The API was extended to expose the state of orchestrated sessions:

-   `GET /api/sessions/{session_id}/context`: Get current `ProtocolContext` values.
-   `POST /api/sessions/{session_id}/context/{key}`: Manually set a context value (for debugging).
-   `GET /api/sessions/{session_id}/stages`: Get protocol stage statuses.
-   `POST /api/sessions/{session_id}/stages/{stage_name}/rerun`: Manually re-run a bootstrap stage.
-   `GET /api/sessions/{session_id}/connection`: Get connection health and statistics.
-   `POST /api/sessions/{session_id}/connection/reconnect`: Force reconnection, optionally re-running bootstrap.
-   `GET /api/sessions/{session_id}/heartbeat`: Get heartbeat health and timing.
-   `POST /api/sessions/{session_id}/execution/replay`: Modified to support replay modes and context reconstruction.

---

## UI Architecture

The UI (`core/ui/spa/`) was significantly updated to provide visibility and control over orchestrated sessions.

-   **Sessions Page**: Displays health indicators for connection, heartbeat, and context for each session.
-   **Session Detail Panel**: Provides an expanded view with:
    -   A visual representation of the `PROTOCOL STACK` and current stage status.
    -   Real-time view of `SESSION CONTEXT` values.
    -   Dedicated panels for `CONNECTION` status and `HEARTBEAT` status, with manual controls (e.g., `Force Reconnect`).
    -   `STATE COVERAGE` for the active `fuzz_target` stage.
-   **New Session Dialog**: Clearly displays the protocol stack, connection, and heartbeat configuration when selecting an orchestrated plugin.
-   **Analysis Page**: Execution history includes `stage_name` and `context_snapshot`. Replay options allow selection of replay mode (`fresh`, `stored`, `skip`) and delay.

---

## Storage Schema Changes

The SQLite database (`data/correlation.db`) and `FuzzSession` model were extended:

### `sessions` Table
-   `protocol_stack_config` (JSON)
-   `current_stage` (TEXT)
-   `context` (JSON snapshot)
-   `connection_mode` (TEXT)
-   `reconnect_count` (INTEGER)
-   `heartbeat_enabled` (INTEGER)
-   `heartbeat_last_sent`, `heartbeat_last_ack` (ISO timestamp TEXT)
-   `heartbeat_failures` (INTEGER)

### `executions` Table
-   `stage_name` (TEXT)
-   `context_snapshot` (JSON)
-   `connection_sequence` (INTEGER)
-   `parsed_fields` (JSON)

---

## Testing Strategy

Comprehensive unit, integration, and end-to-end tests were developed for each component and for the full orchestrated session flow. This includes:
-   **Unit Tests**: For `ProtocolContext`, `ProtocolParser` changes, `StageRunner` logic, `ConnectionManager` threading, `HeartbeatScheduler` timing.
-   **Integration Tests**: For how these components interact, e.g., `bootstrap` exporting to context, heartbeat coordinating with fuzz loop.
-   **End-to-End Tests**: Full orchestrated session runs from API creation to replay, verifying all states and data flows.

---

## Risks and Mitigations (As Implemented)

| Risk | Mitigation |
|------|------------|
| Heartbeat races with fuzz loop | `ConnectionManager.send_with_lock` (async mutex) |
| Context poisoning from mutation | `mutable: False` on `from_context` fields (plugin schema), `ProtocolParser` validation |
| Bootstrap failure blocks session | `retry` config on stages, clear error messages |
| Replay fidelity loss | Store `parsed_fields` in `TestCaseExecutionRecord`, `fresh` replay mode |
| Persistent connection instability | `on_drop`/`on_error` configs with `reconnect`/`rebootstrap`, backoff, max reconnect limits |
| Plugin complexity increase | Comprehensive documentation, `orchestrated_example` plugin, validation |
| Backward compatibility break | Implicit single-stage wrapper for existing plugins |

---

## Glossary

| Term | Definition |
|------|------------|
| **Bootstrap** | Initial protocol exchange that establishes session state (tokens, keys, etc.). Executed by the `StageRunner`. |
| **ProtocolContext** | Session-scoped key-value store for dynamic values shared between stages. |
| **Protocol Stack** | Ordered sequence of protocol stages (`bootstrap`, `fuzz_target`, `teardown`) defined in a plugin. |
| **Stage** | A single phase within a `protocol_stack`. |
| **Heartbeat** | Periodic keep-alive message to maintain persistent connections. Scheduled by `HeartbeatScheduler`. |
| **Export** | Extracting a value from a response within a stage and storing it in the `ProtocolContext`. |
| **from_context** | A field attribute that instructs the `ProtocolParser` to inject a value from the `ProtocolContext` into an outgoing message. |
| **Parsed Fields** | The structured, parsed representation of a message's bytes into a dictionary of fields and values. Stored in history for replay. |