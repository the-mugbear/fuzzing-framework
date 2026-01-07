# Documentation Index

**Last Updated: 2025-11-25**

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

## Plugin Authoring

| File | Description |
| --- | --- |
| [PLUGIN_AUTHORING_GUIDE.md](PLUGIN_AUTHORING_GUIDE.md) | A complete, in-depth guide to creating, testing, and validating custom protocol plugins. This is the primary guide for adding support for a new protocol. |

## Developer Documentation

These documents are for users who want to contribute to the fuzzer's development or understand its internal architecture.

| File | Description |
| --- | --- |
| [developer/01_architectural_overview.md](developer/01_architectural_overview.md) | A technical overview of the fuzzer's architecture and key components. |
| [developer/02_mutation_engine.md](developer/02_mutation_engine.md) | A deep dive into how test cases and mutations are generated. |
| [developer/03_stateful_fuzzing.md](developer/03_stateful_fuzzing.md) | Describes the stateful fuzzing engine and how it follows a protocol's state machine. |
| [developer/04_corpus_and_crash_triage.md](developer/04_corpus_and_crash_triage.md) | Details on how the fuzzer manages its test case corpus and stores findings. |
| [developer/05_agent_and_core_communication.md](developer/05_agent_and_core_communication.md) | Explains the architecture of distributed fuzzing with agents. |