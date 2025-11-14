# Project Roadmap

This document outlines the development roadmap for the fuzzing framework. The items are categorized by their current status and priority.

## Near-Term Priorities (Next 1-3 Months)
### 1. Enhanced Mutators

- **Length-Value Mismatch Mutator**: A new structure-aware mutator that intentionally creates mismatches between a length field and the actual data size (e.g., `length + 1`, `length - 1`). This is highly effective at finding buffer overflows.
- **Smarter Arithmetic and Interesting Value Mutators**: Enhance the existing `ArithmeticMutator` and `InterestingValueMutator` to be structure-aware. They will identify and target specific integer fields from the `data_model`, respecting their size and endianness.

### 2. Improved Crash Triage

- **Automatic Input Minimization**: When a crash occurs with a large input, it can be difficult to identify the root cause. This feature will add a tool to automatically "shrink" the crashing test case to the smallest possible version that still triggers the bug, making debugging much faster.

### 3. Streamlined Plugin Authoring

- **Live Plugin Validator in the UI**: An interactive UI page where a developer can paste their `data_model` and a raw packet (in hex) to see a live, color-coded breakdown of how the fuzzer parses it. This will dramatically speed up the process of creating and debugging new protocol plugins.

## Mid-Term Goals (3-6 Months)
### 1. Advanced Mutators

- **Dictionary/Keyword Mutator**: A new mutator for text-based protocols that replaces known keywords (e.g., `GET`, `USER`) with other keywords or common "garbage" strings. This will require adding a `dictionary` field to the protocol plugin schema.
- **Delimiter Mutator**: A mutator that focuses on manipulating delimiters (e.g., newlines, commas) in protocols that use them, to find parsing and off-by-one errors.

### 2. Advanced Crash Triage

- **Automatic Crash Deduplication**: Implement algorithms to group similar crashes based on their call stack or crash location. This will help developers quickly identify unique bugs and avoid redundant analysis.

### 3. Fuzzing Strategy Enhancements

- **Adaptive Mutation Strategy**: The fuzzer will track which mutation strategies are most effective at finding new paths or crashes and automatically adjust its parameters (like `structure_aware_weight`) during a session to focus on the most productive techniques.

### 4. Accelerated Plugin Authoring

- **PCAP to Plugin Converter**: A powerful tool that can analyze a `.pcap` file of captured network traffic and automatically generate a draft of the `data_model` for a new protocol plugin.

## Long-Term Vision (6+ Months)
### 1. Coverage-Guided (Grey-Box) Fuzzing

- **Description**: This remains a top long-term goal. It involves instrumenting the target application to get feedback on which code paths are executed by each test case. The fuzzer will then use this feedback to prioritize mutations that explore new and interesting parts of the code, providing a massive leap in fuzzing effectiveness.
- **Implementation**: This is a major undertaking that will require compiler wrappers, agent enhancements to collect coverage data, and significant changes to the core engine to manage the feedback loop.

### 2. Corpus Management and Optimization

- **Description**: As fuzzing campaigns run, the input corpus can grow large with redundant test cases. This feature will introduce tools to "distill" the corpus by removing inputs that do not contribute unique code coverage, keeping the fuzzer fast and efficient. This is typically implemented alongside coverage-guided fuzzing.

### 3. Automated Protocol Discovery

- **Description**: The ultimate goal is to move towards a system that requires less manual effort to define protocols. This would involve researching and implementing techniques for automated protocol learning by observing and analyzing valid network traffic to infer message formats, fields, and state transitions.