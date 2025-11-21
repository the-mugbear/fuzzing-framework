# 1. Architectural Overview

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
*   **Fuzz Orchestrator (`orchestrator.py`)**: The brain of the fuzzer. It is responsible for running the main fuzzing loop, which consists of several key stages:
    1.  **Session Management**: Starts, stops, and monitors fuzzing sessions based on user requests.
    2.  **Test Case Generation**: In each iteration, it selects a "seed" from the corpus and passes it to the `MutationEngine` to create a new, unique test case.
    3.  **Execution**: It sends the generated test case to the target application. This can be done directly from the core or delegated to a remote agent.
    4.  **Result Handling**: It monitors the outcome of the execution (e.g., success, hang, crash) and records the results. Crash-inducing test cases are saved as "findings."

### 2. Mutation Engine (`core/engine/mutators.py` & `structure_mutators.py`)

This component is responsible for altering seed data to create new test cases. It supports a hybrid approach to mutation:

*   **Byte-Level Mutations**: Simple, fast, and protocol-agnostic mutations that operate directly on raw bytes (e.g., bit flips, byte flips, arithmetic operations). These are effective at finding shallow bugs.
*   **Structure-Aware Mutations**: An intelligent mode that uses the protocol's `data_model` (from a plugin) to perform "smart" mutations. It parses a seed into its constituent fields, mutates a field's value in a type-aware manner, and then serializes it back into a valid message, automatically fixing dependent fields like lengths and checksums.

### 3. Protocol Plugins & Parser (`core/plugins/` & `core/engine/protocol_parser.py`)

*   **Plugins**: Self-contained Python files that provide the fuzzer with the domain-specific knowledge required to test a protocol. Each plugin defines:
    *   A **`data_model`**: Describes the structure of the protocol's messages.
    *   A **`state_model`** (optional): Describes the protocol's state machine for stateful fuzzing.
    *   A **`validate_response`** function (optional): A "specification oracle" to detect logical bugs in the target's responses.
*   **Protocol Parser**: This component uses the `data_model` to perform bidirectional conversion between raw bytes and a structured dictionary of fields. This is the key that enables structure-aware fuzzing.

### 4. Stateful Fuzzer (`core/engine/stateful_fuzzer.py`)

This module manages fuzzing for stateful protocols. When a plugin provides a `state_model`, this component ensures that the fuzzer sends messages in a valid sequence, allowing it to bypass initial validation and test deeper application logic.

### 5. Corpus & Crash Triage (`core/corpus/store.py`)

*   **Corpus Store**: Manages the collection of test cases. This includes the initial seeds provided by the user and any new, interesting test cases discovered by the fuzzer.
*   **Crash Reporter**: When a crash is detected, this component saves the exact input that caused it, along with detailed metadata, to the `data/crashes` directory. This ensures all findings are reproducible.

### 6. Agents (`agent/`)

*   **Agent (`main.py`)**: A lightweight, standalone Python process that can be run on a remote machine. It polls the Core API for work, executes test cases against its assigned target, and reports back the results, including health telemetry like CPU and memory usage.
*   **Agent Manager (`core/agents/manager.py`)**: Resides in the core and manages the pool of registered agents. It queues work for agents and tracks their status.

### 7. Web UI (`core/ui/spa/`)

A modern React-based Single Page Application (SPA) that provides a user-friendly interface for controlling the fuzzer and visualizing results. It communicates with the Core API via REST calls. The UI also now integrates all user guides, providing a seamless documentation experience.

## The Fuzzing Lifecycle

A typical fuzzing session proceeds as follows:

1.  **User Action**: A user initiates a fuzzing session through the Web UI or by calling the REST API, specifying the protocol, target, and other configuration options.
2.  **Session Initialization**: The `FuzzOrchestrator` creates a new session. It loads the specified protocol plugin and its associated `data_model` and seeds.
3.  **The Fuzzing Loop Begins**: The orchestrator enters its main loop.
4.  **Seed Selection**: An initial seed is selected from the corpus. In a stateful session, a seed is chosen that is valid for the protocol's current state.
5.  **Mutation**: The seed is passed to the `MutationEngine`, which applies one or more mutation strategies to generate a new test case.
6.  **Execution**:
    *   **Core Mode**: The orchestrator sends the test case directly to the target.
    *   **Agent Mode**: The orchestrator enqueues the test case with the `AgentManager`. A polling agent retrieves the test case and sends it to the target.
7.  **Monitoring & Response**: The component that executed the test (either the core or an agent) monitors the target's response. It looks for crashes (e.g., connection closed unexpectedly), hangs (e.g., no response within a timeout), or other anomalies.
8.  **Result Reporting**: The result is reported back to the `FuzzOrchestrator`.
9.  **Crash Handling**: If a crash was detected, the `CrashReporter` saves the test case and all relevant metadata as a "finding" in the `data/crashes` directory.
10. **Iteration**: The loop repeats, continuously generating and executing new test cases until the user stops the session or a predefined limit is reached.

This modular architecture allows each component to be developed, tested, and improved independently, while the plugin-driven design makes the entire system highly extensible to new and unknown protocols.