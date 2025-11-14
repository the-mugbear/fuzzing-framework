# Fuzzing Engine: Developer Documentation

## 1. Architectural Overview

The fuzzing engine is a modular, plugin-driven system designed to test the robustness of network protocols. It operates by generating and executing a vast number of mutated test cases against a target application and monitoring for crashes or other anomalous behavior.

The architecture is centered around the **`FuzzOrchestrator`**, which manages the entire fuzzing lifecycle. Its primary responsibility is to run the main fuzzing loop, which consists of several key stages:

1.  **Session Creation**: The orchestrator creates a fuzzing session, which can be stateless or stateful, depending on the protocol's definition in its plugin.
2.  **Test Case Generation**: In each loop iteration, a new test case is generated. This is not done from scratch. Instead, a "seed" test case is selected from the corpus and subjected to mutation.
3.  **Execution**: The generated test case is sent to the target application. This can be done directly or delegated to a remote agent for scalability.
4.  **Result Handling**: The orchestrator monitors the outcome of the execution. If a crash is detected, the test case that caused it (a "finding") is saved for later analysis.

The entire process is guided by a **protocol plugin**, which provides the necessary domain-specific knowledge, such as the protocol's message structure (`data_model`) and, for stateful protocols, its state machine (`state_model`). The user interacts with the system through a modern **React Single Page Application (SPA)**, which now also integrates all user guides previously served as static HTML files.

### Key Components

The system is composed of several key modules that work in concert:

- **Orchestrator (`core/engine/orchestrator.py`)**: The heart of the fuzzer. It coordinates all other components and manages the high-level fuzzing loop.
- **Mutation Engine (`core/engine/mutators.py`)**: Responsible for applying mutations to seed test cases. It supports both simple byte-level mutations and sophisticated structure-aware mutations.
- **Protocol Parser (`core/engine/protocol_parser.py`)**: The key to "intelligent" fuzzing. It uses the `data_model` from a plugin to parse raw bytes into a structured format and serialize them back, automatically fixing fields like checksums or length prefixes.
- **Stateful Fuzzer (`core/engine/stateful_fuzzer.py`)**: Manages fuzzing for stateful protocols, ensuring that messages are sent in a valid sequence according to the plugin's `state_model`.
- **Corpus Store (`core/corpus/store.py`)**: Manages the collection of seed test cases and stores crash-inducing findings.
- **Agent Manager (`core/agents/manager.py`)**: Handles the distribution of test case execution to remote agents, enabling scaled-out fuzzing campaigns.
- **Plugins (`core/plugins/`)**: Self-contained modules that define how to fuzz a specific protocol. They provide the essential metadata that the engine relies on.

This modular design allows the engine to be easily extended to support new protocols and new mutation strategies. The following sections will dive deeper into each of these components.
