# Project Roadmap

This document outlines the roadmap for improving the fuzzing tool. The items are categorized by priority, from critical near-term features to long-term enhancements.

## Near-Term Priorities (Critical for Effectiveness)

### 1. Stateful Protocol Fuzzing

**Problem:** The current fuzzing engine is stateless. It sends mutated data without respecting the logical order of a protocol's state machine (e.g., sending data before authentication). This makes it highly inefficient against most real-world network protocols.

**Solution:**
- Modify the core fuzzing engine (`FuzzOrchestrator`) to read and interpret the `state_model` defined in protocol plugins.
- Implement logic to traverse the protocol's state machine, sending valid sequences of messages.
- Focus mutations on the data *within* messages appropriate for the current state, rather than mutating the message sequence itself.

## Mid-Term Goals (Major Enhancements)

### 2. Feedback-Driven (Grey-Box) Fuzzing

**Problem:** The fuzzer currently operates in a "black-box" mode, with no insight into the target application's internal state. This is inefficient, as it cannot intelligently prioritize inputs that explore new functionality.

**Solution:**
- Integrate a feedback mechanism based on code coverage.
- **Instrumentation:** Require the target application to be compiled with instrumentation (e.g., using compiler wrappers like `afl-gcc`/`afl-clang` or LLVM Sanitizers).
- **Agent Enhancement:** The agent will be responsible for running the instrumented target and collecting the coverage data (e.g., from a shared memory map).
- **Engine Enhancement:** The fuzzing engine will use this coverage feedback to identify "interesting" test cases (those that discover new code paths) and save them to the corpus, prioritizing them for future mutations.

### 3. Advanced Crash Triage

**Problem:** Finding a crash is only the first step. Analyzing and managing crashes is a major bottleneck for developers.

**Solution:**
- **Crash Deduplication:** Implement algorithms to group crashes that have the same root cause, reducing redundant analysis work.
- **Test Case Minimization:** Add a tool to automatically shrink a crashing test case to the smallest possible version that still triggers the bug.
- **Exploitability Analysis:** Integrate with tools (like `!exploitable` for Windows or similar Linux GDB scripts) to help classify the security severity of a crash.

## Long-Term Vision (Future Development)

### 4. Corpus Management & Optimization

**Problem:** Over long-running fuzzing campaigns, the input corpus can grow large with redundant test cases, slowing down the fuzzer.

**Solution:**
- Implement corpus distillation and minimization tools. These tools periodically review the corpus and remove inputs that do not contribute unique code coverage, keeping the corpus small and fast.

### 5. Automated Protocol Discovery

**Problem:** The current model requires a user to manually define the protocol structure and state machine.

**Solution:**
- Explore techniques for automated protocol learning. This could involve:
  - Observing and analyzing valid network traffic between a client and server.
  - Using machine learning to infer message formats, fields, and state transitions.
