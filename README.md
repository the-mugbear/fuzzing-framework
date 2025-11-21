# Proprietary Protocol Fuzzer

A portable, extensible fuzzing stack for proprietary network protocols. The Core orchestrator (FastAPI + web UI) drives a powerful mutation engine and corpus store, while lightweight agents can be deployed to relay test cases to remote targets and stream back telemetry.

This fuzzer is designed to be "intelligent." Through the use of **protocol plugins**, it can learn the structure and rules of a protocol, allowing it to perform structure-aware mutations and test deep, stateful application logic that would be missed by simpler, purely random fuzzers.

## Key Features

-   **Structure-Aware & Stateful Fuzzing**: Understands your protocol's message structure and state machine to generate valid, complex test cases.
-   **Declarative Protocol Modeling**: Define protocol message formats, state transitions, and even complex behaviors like checksums and sequence numbers in simple Python dictionaries.
-   **Hybrid Mutation Engine**: Combines fast, simple byte-level mutations (e.g., bit flips, havoc) with intelligent, structure-aware mutations.
-   **Distributed Fuzzing**: Scale your fuzzing campaigns by distributing the workload to multiple remote agents.
-   **Modern Web UI**: A user-friendly React-based dashboard for managing sessions, viewing real-time statistics, and inspecting findings.
-   **Reproducible Crashes**: Every crash is automatically saved with the exact input that caused it, making bugs easy to reproduce and analyze.

## Getting Started

The fastest way to get started is with Docker. This will build and run the entire stack, including the core fuzzer, a test target, and an agent.

```bash
# Build and start all services
make docker-up
```

Once the services are running, you can access the web UI at **http://localhost:8000**.

For detailed setup instructions, including how to run the fuzzer locally for development, please see the **[Quick Start Guide](QUICKSTART.md)**.

## Documentation

This repository contains a comprehensive suite of documentation to help you get started, create your own protocol plugins, and contribute to the project.

**For a complete and curated list of all documentation, please see the [Documentation Index](docs/README.md).**

Key documents include:
-   **[QUICKSTART.md](QUICKSTART.md)**: Get the fuzzer running in 5 minutes.
-   **[FUZZING_GUIDE.md](docs/FUZZING_GUIDE.md)**: A practical guide to fuzzing concepts and campaign strategy.
-   **[PROTOCOL_TESTING.md](docs/PROTOCOL_TESTING.md)**: A complete, in-depth guide to creating custom protocol plugins.
-   **[Developer Documentation](docs/developer/)**: A collection of deep-dive documents explaining the architecture of each of the fuzzer's subsystems.

## Project Vision

To learn more about the future direction of the project, planned features, and architectural improvements, see the following documents:

-   **[Roadmap](roadmap.md)**
-   **[Architecture Improvements Plan](ARCHITECTURE_IMPROVEMENTS_PLAN.md)**