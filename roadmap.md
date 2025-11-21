# Project Roadmap

This document outlines the future direction and planned features for the protocol fuzzer.

## Near-Term (1-3 Months)

*   **Richer Crash Triage:**
    *   Implement automated crash bucketing to group similar crashes.
    *   Begin work on basic automated root cause analysis for common vulnerability classes.
*   **Improved Protocol Definition Workflow:**
    *   Create a UI-based protocol definition editor to lower the barrier to entry.
    *   Develop a plugin validation tool to provide better feedback on custom plugins.
*   **Checksum Support:**
    *   Add built-in support for common checksum algorithms (CRC32, Fletcher-16) in the `ProtocolParser`.

## Mid-Term (3-6 Months)

*   **Coverage-Guided Fuzzing (Phase 1):**
    *   Integrate with a lightweight coverage mechanism (e.g., SanitizerCoverage).
    *   Enhance the agent to collect and report basic block coverage.
    *   Use coverage information to prioritize interesting mutations.
*   **Protocol Discovery from PCAP:**
    *   Implement a tool to analyze `.pcap` files and generate draft protocol plugins.
*   **Advanced Corpus Management:**
    *   Add corpus minimization and distillation tools.

## Long-Term (6-12+ Months)

*   **Full Coverage-Guided Fuzzing:**
    *   Support for advanced instrumentation frameworks (e.g., Intel PT).
*   **Proxy-based Protocol Learning:**
    *   Implement a proxy mode for real-time protocol learning.
*   **Support for Encrypted Protocols:**
    *   Add native TLS support and hooks for custom encryption schemes.
