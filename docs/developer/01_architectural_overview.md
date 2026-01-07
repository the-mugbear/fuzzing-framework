# 1. Architectural Overview

**Last Updated: 2025-11-25**

This document provides a high-level technical overview of the fuzzer's architecture. It is intended for developers who want to understand how the system works, contribute to its development, or debug complex issues.

## Core Philosophy

The fuzzer is designed as a modular, plugin-driven system for testing the robustness and security of proprietary network protocols. Its core philosophy is to separate the general-purpose fuzzing engine from the protocol-specific knowledge. This separation is achieved through **protocol plugins**, which act as a "driver" for the fuzzer, teaching it the language of the target protocol.

The system is built around a central **Orchestrator** that manages the entire fuzzing lifecycle, from test case generation to crash detection. It can operate in a standalone mode or distribute work to remote **Agents** for scaled-out fuzzing campaigns.

## High-Level Diagram

```
┌───────────────────┐      ┌───────────────────────────┐      ┌───────────────────┐
│      Web UI       │      │         Core API          │      │       Agent       │
│ (React SPA)       ├─────▶│ (FastAPI + Orchestrator)  │◀────▶│  (Remote Worker)  │
└───────────────────┘      └───────────────────────────┘      └───────────────────┘
                             │             ▲                      │
                             │             │ Results              │ Test Cases
                             ▼             │                      ▼
                      ┌────────────────┐ ┌─┴────────────────┐   ┌───────────────────┐
                      │ Protocol       │ │ Corpus & Crashes │   │      Target       │
                      │ Plugins        │ │ (File System)    │   │ (Application)     │
                      └────────────────┘ └──────────────────┘   └───────────────────┘
```

## Key Components

The system is composed of several key Python modules that work in concert.

### 1. Core API & Orchestrator (`core/api/` & `core/engine/orchestrator.py`)

*   **Core API (`server.py`)**: A FastAPI application that serves as the main entry point to the system. It exposes a REST API for managing fuzzing sessions, viewing results, and configuring the fuzzer. It also serves the React-based web UI.
*   **Fuzz Orchestrator (`orchestrator.py`)**: The brain of the fuzzer. It is responsible for running the main fuzzing loop, which consists of several key stages, including session management, test case generation, execution, and result handling.

### 2. Mutation Engine (`core/engine/mutators.py` & `structure_mutators.py`)

This component is responsible for altering seed data to create new test cases. It supports byte-level mutations and structure-aware mutations.

### 3. Protocol Plugins & Parser (`core/plugins/` & `core/engine/protocol_parser.py`)

*   **Plugins**: Self-contained Python files that provide the fuzzer with the domain-specific knowledge required to test a protocol. They define a `data_model`, an optional `state_model`, and an optional `validate_response` function.
*   **Protocol Parser**: Uses the `data_model` to perform bidirectional conversion between raw bytes and a structured dictionary of fields.

### 4. Stateful Fuzzing (`core/engine/stateful_fuzzer.py`)

*   **StatefulFuzzingSession**: When a plugin provides a `state_model`, the orchestrator uses this class to manage the fuzzing session according to the protocol's state machine, ensuring messages are sent in a valid sequence.

### 5. Corpus & Crash Triage (`core/corpus/store.py` & `core/engine/crash_handler.py`)

*   **CorpusStore**: Manages the collection of seeds and crash-inducing test cases (findings).
*   **CrashReporter**: Saves the details of any crash-inducing test case to the `data/crashes` directory.

### 6. Advanced Logic Components

*   **ResponsePlanner (`core/engine/response_planner.py`)**: When a plugin defines `response_handlers`, this component evaluates server responses and queues follow-up messages, enabling the fuzzer to navigate complex, interactive protocols.
*   **BehaviorProcessor (`core/protocol_behavior.py`)**: Applies deterministic transformations to a test case before it is sent, such as updating a sequence number or timestamp, based on `behavior` rules in the plugin.
*   **ExecutionHistoryStore (`core/engine/history_store.py`)**: Records every test case execution, including sent data, received data, and timestamps, for later analysis and replay.

### 7. Agents (`agent/main.py` & `core/agents/manager.py`)

*   **Agent**: A lightweight, standalone process that polls the Core API for work, executes test cases against its assigned target, and reports back the results.
*   **Agent Manager**: Manages the pool of registered agents and queues work for them.

### 8. Web UI (`core/ui/spa/`)

A React-based Single Page Application that provides a user-friendly interface for controlling the fuzzer and visualizing results.

## The Fuzzing Lifecycle

A typical fuzzing session proceeds as follows:

1.  **User Action**: A user initiates a fuzzing session through the Web UI or REST API.
2.  **Session Initialization**: The `FuzzOrchestrator` creates a new session and loads the protocol plugin.
3.  **The Fuzzing Loop Begins**: The orchestrator enters its main loop.
4.  **Test Case Selection**: An input is selected for mutation. This could be:
    *   A seed from the corpus, chosen based on the protocol's current state if a `state_model` is used.
    *   A follow-up message queued by the `ResponsePlanner` based on a previous server response.
5.  **Mutation**: The selected input is passed to the `MutationEngine` to generate a new test case.
6.  **Behavior Application**: The `BehaviorProcessor` applies any deterministic rules (e.g., incrementing sequence numbers) to the mutated data.
7.  **Execution**: The final test case is sent to the target, either directly from the core or via an agent.
8.  **Monitoring & Response**: The executor monitors the target for crashes, hangs, or other anomalies.
9.  **Result Reporting**: The result is reported back to the `FuzzOrchestrator`.
10. **Crash Handling**: If a crash was detected, the `CrashReporter` saves the finding.
11. **History Recording**: The `ExecutionHistoryStore` records the details of the sent test case and the received response.
12. **Response Planning**: The `ResponsePlanner` analyzes the server's response and, if it matches a rule in the plugin, queues a new follow-up message.
13. **Iteration**: The loop repeats until the user stops the session or a limit is reached.

This modular architecture allows each component to be developed, tested, and improved independently, while the plugin-driven design makes the entire system highly extensible to new and unknown protocols.
