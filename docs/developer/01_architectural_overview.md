# 1. Architectural Overview

**Last Updated: 2026-01-30**

This document provides a high-level technical overview of the fuzzer's architecture. It is intended for developers who want to understand how the system works, contribute to its development, or debug complex issues.

## Core Philosophy

The fuzzer is designed as a modular, plugin-driven system. Its core philosophy is to separate the general-purpose fuzzing engine from protocol-specific knowledge. This is achieved through **protocol plugins**, which act as "drivers," teaching the fuzzer the language of the target protocol.

The system is built around a central **FuzzOrchestrator** that manages the entire fuzzing lifecycle. It now supports both simple, stateless fuzzing and complex, **Orchestrated Sessions** for stateful protocols that require handshakes and persistent connections.

## High-Level Diagram: Orchestrated Session

```
                                 ┌───────────────────────────┐
                                 │         Core API          │
                                 │ (FastAPI Server)          │
                                 └───────────────────────────┘
                                             │ ▲
                                     (Control & View)
                                             │ │
┌───────────────────┐              ┌───────────────────────────┐              ┌───────────────────┐
│      Web UI       │◀────────────▶│      FuzzOrchestrator     │◀────────────▶│       Agent       │
│    (React SPA)    │              │ (The Brain)               │              │  (Remote Worker)  │
└───────────────────┘              └───────────┬───────────────┘              └──────────┬────────┘
                                               │                                         │
                      ┌────────────────────────┼─────────────────────────┐               │
                      │                        │                         │               │
                      ▼                        ▼                         ▼               ▼
┌───────────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐   ┌───────────────────┐
│        StageRunner        │  │  HeartbeatScheduler   │  │   ConnectionManager   │   │      Target       │
│ (Executes protocol_stack) │  │ (Sends PINGs)         │  │(Manages Sockets)      │   │ (Application)     │
└───────────┬───────────────┘  └───────────┬───────────┘  └───────────┬───────────┘   └───────────────────┘
            │                              │                         │
            └───────────────┐              │            ┌────────────┘
                            │              │            │
                            ▼              ▼            ▼
                           ┌──────────────────────────────────┐
                           │         ProtocolContext          │
                           │(Shared State: e.g., session_token)│
                           └──────────────────────────────────┘
```

## Key Components

### 1. FuzzOrchestrator (`core/engine/orchestrator.py`)
The "brain" of the fuzzer. It manages the entire lifecycle of a fuzzing session. In an orchestrated session, it is responsible for:
-   Initiating the `StageRunner` to execute the `bootstrap` process.
-   Creating and managing the `ProtocolContext`.
-   Starting the `HeartbeatScheduler` for the session.
-   Running the main `fuzz_target` loop, injecting context values into test cases.
-   Coordinating self-healing by providing a `reconnect` callback to the heartbeat scheduler.

### 2. StageRunner (`core/engine/stage_runner.py`)
This component is responsible for executing the sequential stages (`bootstrap`, `teardown`) of an orchestrated session's `protocol_stack`. It sends the pre-defined messages for each step, validates the server's responses, and, crucially, **exports** values from the responses into the `ProtocolContext`.

### 3. ProtocolContext (`core/engine/protocol_context.py`)
A simple, per-session, key-value store. It acts as the "shared memory" between stages in an orchestrated session. A `bootstrap` stage can write a session token into the context, and the `fuzz_target` and `heartbeat` stages can read that token to maintain a valid session.

### 4. ConnectionManager (`core/engine/connection_manager.py`)
Manages persistent TCP connections for orchestrated sessions. It provides a thread-safe `send_with_lock` method to prevent race conditions between the main fuzzing loop and the background heartbeat task when both are trying to use the same socket.

### 5. HeartbeatScheduler (`core/engine/heartbeat_scheduler.py`)
For sessions that require it, this component runs a concurrent `asyncio` task that sends periodic keep-alive messages (heartbeats). If the heartbeat fails (e.g., the connection is dropped), it can trigger a `reconnect` action, prompting the `FuzzOrchestrator` to re-run the bootstrap process, making the session self-healing.

### 6. Mutation Engine (`core/engine/mutators.py`, `structure_mutators.py`)
This component alters seed data to create new test cases. It supports both "dumb" byte-level mutations and "smart" structure-aware mutations that respect the protocol's grammar.

### 7. Protocol Plugins & Parser (`core/plugins/`, `core/engine/protocol_parser.py`)
-   **Plugins**: The core of the fuzzer's extensibility. They define the `data_model` (structure), `state_model` (behavior), and orchestration logic (`protocol_stack`, `heartbeat`, etc.) of a protocol.
-   **Parser**: A bidirectional engine that uses a plugin's `data_model` to convert between raw bytes and a structured dictionary of fields.

### 8. Data Persistence
-   **CorpusStore**: Manages interesting test cases (seeds).
-   **CrashReporter**: Saves crash data.
-   **ExecutionHistoryStore**: Records every test case to a high-performance SQLite database for later analysis and visualization.

## The Orchestrated Fuzzing Lifecycle

A modern, stateful fuzzing session proceeds as follows:

1.  **User Action**: A user starts a session for a plugin that contains a `protocol_stack`.
2.  **Session Initialization**: The `FuzzOrchestrator` creates a session and identifies that it is an orchestrated session.
3.  **Bootstrap**: The `FuzzOrchestrator` invokes the `StageRunner` to execute the `bootstrap` stage(s).
4.  **Handshake & Export**: The `StageRunner` sends the handshake message(s). Upon receiving a valid response, it **exports** the required data (e.g., a `session_token`) into the `ProtocolContext`.
5.  **Heartbeat Start**: If a `heartbeat` is configured, the `FuzzOrchestrator` starts the `HeartbeatScheduler` in a background task. The heartbeat messages can now use values from the context (like the `session_token`).
6.  **Fuzzing Loop Begins**: The orchestrator starts the main fuzzing loop for the `fuzz_target` stage.
7.  **Test Case Selection & Context Injection**: An input is selected from the corpus. Before mutation, the orchestrator **injects** any required values from the `ProtocolContext` into the test case (e.g., placing the `session_token` into the correct field).
8.  **Mutation & Execution**: The test case is mutated and sent to the target via the `ConnectionManager`'s locked transport.
9.  **Monitoring & Result Handling**: The result (pass, crash, hang) is reported back.
10. **Self-Healing (on failure)**: If the connection is dropped, the background heartbeat will fail. After a configured threshold, it calls the `reconnect` callback provided by the `FuzzOrchestrator`. This triggers the entire process to start again from **Step 3 (Bootstrap)**, creating a new connection and authenticating a new session automatically before resuming fuzzing.
11. **Iteration**: The loop (Steps 7-9) repeats until the user stops the session.

This architecture enables the fuzzer to test complex, modern protocols that require authenticated, persistent sessions, and to recover automatically from network instability.