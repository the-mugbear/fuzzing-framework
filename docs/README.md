# Documentation Index

**Last Updated: 2026-01-06**

Welcome to the documentation for the protocol fuzzer. This index provides a curated list of the most important documents in the repository, organized by audience.

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

## Plugin Development

| File | Description |
| --- | --- |
| [PROTOCOL_PLUGIN_GUIDE.md](PROTOCOL_PLUGIN_GUIDE.md) | Complete guide to creating, testing, debugging, and validating custom protocol plugins. Includes step-by-step examples, validation strategies, troubleshooting, and advanced testing techniques. This is the definitive guide for adding support for new protocols. |
| [PROTOCOL_SERVER_TEMPLATES.md](PROTOCOL_SERVER_TEMPLATES.md) | Templates and examples for creating test servers that implement your protocol. |
| [TEMPLATE_QUICK_REFERENCE.md](TEMPLATE_QUICK_REFERENCE.md) | Quick reference for plugin template syntax and common patterns. |

## Developer Documentation

These documents are for users who want to contribute to the fuzzer's development or understand its internal architecture.

| File | Description |
| --- | --- |
| [developer/01_architectural_overview.md](developer/01_architectural_overview.md) | A technical overview of the fuzzer's architecture and key components. |
| [developer/02_mutation_engine.md](developer/02_mutation_engine.md) | A deep dive into how test cases and mutations are generated. |
| [developer/03_stateful_fuzzing.md](developer/03_stateful_fuzzing.md) | Describes the stateful fuzzing engine and how it follows a protocol's state machine. |
| [developer/04_corpus_and_crash_triage.md](developer/04_corpus_and_crash_triage.md) | Details on how the fuzzer manages its test case corpus and stores findings. |
| [developer/05_agent_and_core_communication.md](developer/05_agent_and_core_communication.md) | Explains the architecture of distributed fuzzing with agents. |

## Archive

Historical implementation logs and completed feature planning documents.

| File | Description |
| --- | --- |
| [archive/FIXES_IMPLEMENTED.md](archive/FIXES_IMPLEMENTED.md) | Implementation log for critical fixes (Sessions 2-3, 2026-01-06). **Superseded by [CHANGELOG.md](../CHANGELOG.md)**. |
| [archive/PHASE2_ENHANCEMENTS.md](archive/PHASE2_ENHANCEMENTS.md) | Implementation log for Phase 2 features (state graph visualization, 2025-11). |
| [archive/VISUALIZATION_IMPROVEMENTS.md](archive/VISUALIZATION_IMPROVEMENTS.md) | Implementation log for graph visualization fixes (2025-11). |
| [archive/MUTATION_TYPES_ENHANCEMENT.md](archive/MUTATION_TYPES_ENHANCEMENT.md) | Feature planning document for mutation enhancements (2025-11). |
| [archive/STATE_FUZZING_TEST_REPORT.md](archive/STATE_FUZZING_TEST_REPORT.md) | Test report for stateful fuzzing implementation (2025-11). |