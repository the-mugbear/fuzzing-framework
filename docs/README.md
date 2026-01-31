# Documentation Index

**Last Updated: 2026-01-31**

Welcome to the documentation for the protocol fuzzer. This index provides a curated list of the most important documents in the repository, organized by audience.

> **Tip:** All documentation is now viewable directly in the web UI via the **Documentation Hub** page. Click "Read documentation" on any card to view the content without leaving the console.

## Getting Started

| File | Description |
| --- | --- |
| [QUICKSTART.md](QUICKSTART.md) | A step-by-step guide to get the fuzzer running in 5 minutes using Docker or a local setup. |

## User Guides

These documents provide the essential information needed to run a successful fuzzing campaign.

| File | Description |
| --- | --- |
| [USER_GUIDE.md](USER_GUIDE.md) | A practical guide to fuzzing concepts, campaign strategy, and troubleshooting common issues. |
| [STATE_COVERAGE_GUIDE.md](STATE_COVERAGE_GUIDE.md) | Guide to state coverage tracking and targeted fuzzing modes (random, breadth-first, depth-first, targeted). |
| [MUTATION_STRATEGIES.md](MUTATION_STRATEGIES.md) | Explanation of mutation strategies: structure-aware vs byte-level mutations, hybrid mode, and when to use each. |

## Plugin Development & Advanced Features

| File | Description |
| --- | --- |
| [PROTOCOL_PLUGIN_GUIDE.md](PROTOCOL_PLUGIN_GUIDE.md) | The definitive guide to creating custom protocol plugins. Covers everything from basic template syntax to advanced validation and testing techniques. |
| [ORCHESTRATED_SESSIONS_GUIDE.md](ORCHESTRATED_SESSIONS_GUIDE.md) | A guide to using multi-protocol orchestration for complex, stateful targets that require handshakes, authentication, or other sequential interactions. Covers session context, heartbeats, and self-healing connections. |
| [TEMPLATE_QUICK_REFERENCE.md](TEMPLATE_QUICK_REFERENCE.md) | Quick reference for plugin template syntax and common patterns. |
| [PROTOCOL_SERVER_TEMPLATES.md](PROTOCOL_SERVER_TEMPLATES.md) | Templates and examples for creating test servers that implement your protocol. |

## Developer Documentation

These documents are for users who want to contribute to the fuzzer's development or understand its internal architecture.

| File | Description |
| --- | --- |
| [developer/01_architectural_overview.md](developer/01_architectural_overview.md) | A high-level technical overview of the fuzzer's architecture and key components. |
| [developer/ORCHESTRATED_SESSIONS_ARCHITECTURE.md](developer/ORCHESTRATED_SESSIONS_ARCHITECTURE.md) | A deep-dive into the architecture of multi-protocol support, session context, and the heartbeat scheduler. |
| [developer/02_mutation_engine.md](developer/02_mutation_engine.md) | A deep dive into how test cases and mutations are generated. |
| [developer/03_stateful_fuzzing.md](developer/03_stateful_fuzzing.md) | Describes the stateful fuzzing engine and how it follows a protocol's state machine. |
| [developer/04_data_management.md](developer/04_data_management.md) | Details on how the fuzzer manages its test case corpus, session history, and crash data. |
| [developer/05_agent_and_core_communication.md](developer/05_agent_and_core_communication.md) | Explains the architecture of distributed fuzzing with agents. |
| [developer/06_first_debug_session.md](developer/06_first_debug_session.md) | A practical guide for setting up a development environment and debugging a fuzzing session. |


## Archive

Historical implementation logs and completed feature planning documents.

| File | Description |
| --- | --- |
| [archive/FIXES_IMPLEMENTED.md](archive/FIXES_IMPLEMENTED.md) | Implementation log for critical fixes (Sessions 2-3, 2026-01-06). **Superseded by [CHANGELOG.md](../CHANGELOG.md)**. |
| [archive/PHASE2_ENHANCEMENTS.md](archive/PHASE2_ENHANCEMENTS.md) | Implementation log for Phase 2 features (state graph visualization, 2025-11). |
| [archive/VISUALIZATION_IMPROVEMENTS.md](archive/VISUALIZATION_IMPROVEMENTS.md) | Implementation log for graph visualization fixes (2025-11). |
| [archive/MUTATION_TYPES_ENHANCEMENT.md](archive/MUTATION_TYPES_ENHANCEMENT.md) | Feature planning document for mutation enhancements (2025-11). |
| [archive/STATE_FUZZING_TEST_REPORT.md](archive/STATE_FUZZING_TEST_REPORT.md) | Test report for stateful fuzzing implementation (2025-11). |