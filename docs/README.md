# Documentation Index

Welcome to the documentation for the protocol fuzzer. This index provides a curated list of the most important documents in the repository, organized by audience.

## For All Users

These documents provide the essential information needed to get started with the fuzzer and run a successful fuzzing campaign.

| File | Description |
| --- | --- |
| [README.md](../README.md) | A high-level overview of the project, its architecture, and key features. **Start here.** |
| [QUICKSTART.md](../QUICKSTART.md) | A step-by-step guide to get the fuzzer running in 5 minutes using Docker or a local setup. |
| [FUZZING_GUIDE.md](FUZZING_GUIDE.md) | A practical guide to fuzzing concepts, campaign strategy, and troubleshooting common issues. |

## For Developers & Plugin Authors

These documents are for users who want to extend the fuzzer by creating their own protocol plugins or contribute to the fuzzer's development.

| File | Description |
| --- | --- |
| [PROTOCOL_TESTING.md](PROTOCOL_TESTING.md) | A complete, in-depth guide to creating, testing, and validating custom protocol plugins. **This is the primary guide for adding support for a new protocol.** |
| [developer/01_architectural_overview.md](developer/01_architectural_overview.md) | A technical overview of the fuzzer's architecture and key components. |
| [developer/02_mutation_engine.md](developer/02_mutation_engine.md) | A deep dive into how test cases and mutations are generated. |
| [developer/03_protocol_plugins_and_parsing.md](developer/03_protocol_plugins_and_parsing.md) | Explains how the fuzzer understands protocol structures through plugins, including advanced logic like calculated fields and response handling. |
| [developer/04_stateful_fuzzing.md](developer/04_stateful_fuzzing.md) | Describes the stateful fuzzing engine and how it follows a protocol's state machine. |
| [developer/05_corpus_and_crash_triage.md](developer/05_corpus_and_crash_triage.md) | Details on how the fuzzer manages its test case corpus and stores findings. |
| [developer/06_agent_and_core_communication.md](developer/06_agent_and_core_communication.md) | Explains the architecture of distributed fuzzing with agents. |

## Project Vision

| File | Description |
| --- | --- |
| [roadmap.md](../roadmap.md) | Outlines the future direction and planned features for the project. |
| [ARCHITECTURE_IMPROVEMENTS_PLAN.md](../ARCHITECTURE_IMPROVEMENTS_PLAN.md) | Describes planned architectural changes to improve performance, scalability, and maintainability. |
