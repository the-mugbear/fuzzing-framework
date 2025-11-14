# Documentation Index

This file provides a curated list of the most important documentation in the repository.

## For All Users

| File | Description |
| --- | --- |
| [README.md](../README.md) | High-level overview of the project, its architecture, and key features. **Start here.** |
| [QUICKSTART.md](../QUICKSTART.md) | A step-by-step guide to get the fuzzer running in 5 minutes using Docker or a local setup. |
| [FUZZING_GUIDE.md](FUZZING_GUIDE.md) | A practical guide to fuzzing concepts, campaign strategy, and troubleshooting. |

## For Developers & Contributors

| File | Description |
| --- | --- |
| [PROTOCOL_TESTING.md](PROTOCOL_TESTING.md) | A complete, in-depth guide to creating, testing, and validating custom protocol plugins. |
| [01_overview.md](developer/01_overview.md) | A technical overview of the fuzzer's architecture and key components. |
| [02_test_case_generation_and_mutation.md](developer/02_test_case_generation_and_mutation.md) | A deep dive into how test cases and mutations are generated. |
| [03_protocol_parsing_and_plugins.md](developer/03_protocol_parsing_and_plugins.md) | Explains how the fuzzer understands protocol structures through plugins. |
| [04_stateful_fuzzing.md](developer/04_stateful_fuzzing.md) | Describes the stateful fuzzing engine and how it follows a protocol's state machine. |
| [05_corpus_and_agents.md](developer/05_corpus_and_agents.md) | Details on how the fuzzer manages its test case corpus and uses distributed agents. |
| [06_advanced_logic.md](developer/06_advanced_logic.md) | Explains advanced features like automatic size calculation and declarative response handling. |