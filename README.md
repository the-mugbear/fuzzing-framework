# Proprietary Protocol Fuzzer - MVP

A portable, extensible fuzzing framework for proprietary network protocols.

## Architecture

- **Core Container**: FastAPI-based orchestrator with REST API and web UI
- **Target Agent**: Lightweight agent that forwards fuzzed inputs to target
- **Plugin System**: Single-file Python protocol definitions
- **Mutation Engine**: Intelligent test case generation
- **Intelligent Oracles**: Multi-layered failure detection

## Quick Start

### Running the Core

```bash
# Install dependencies
pip install -r requirements.txt

# Start the Core API server
python -m core.api.server

# Access web UI at http://localhost:8000
```

### Running the Agent

```bash
# Start the agent (connects to Core)
python -m agent.main --core-url http://localhost:8000
```

### Docker Deployment

```bash
# Build and run Core
docker-compose up core

# Run Agent (separate host)
docker run -e CORE_URL=https://core:8000 fuzzer-agent
```

## Creating a Protocol Plugin

Create a file in `core/plugins/` directory:

```python
# core/plugins/my_protocol.py

data_model = {
    "name": "MyProtocol",
    "blocks": [
        {"name": "header", "type": "bytes", "size": 4, "default": b"MYPK"},
        {"name": "length", "type": "uint32", "endian": "big"},
        {"name": "payload", "type": "bytes", "size_field": "length"},
    ]
}

state_model = {
    "states": ["INIT", "AUTH", "READY"],
    "transitions": [
        {"from": "INIT", "to": "AUTH", "message": "AUTH_REQUEST"},
        {"from": "AUTH", "to": "READY", "message": "AUTH_RESPONSE"},
    ]
}

def validate_response(response):
    """Optional: Custom response validation"""
    return True
```

## Project Status - MVP Complete ✅

**Phase 1 (MVP) Implementation - COMPLETE**

All MVP deliverables have been implemented:

### Core Components ✅
- **FastAPI Server** - Full REST API with endpoint for sessions, plugins, corpus, and agents
- **Orchestrator** - Fuzzing session management and coordination
- **Mutation Engine** - 6 mutation strategies (bitflip, byteflip, arithmetic, interesting values, havoc, splice)
- **Plugin System** - Dynamic protocol loading from Python files
- **Corpus Store** - Seed management and crash/finding persistence (JSON + MessagePack)
- **Web UI** - Real-time dashboard for session control and monitoring

### Agent & Monitoring ✅
- **Target Agent** - Lightweight agent with Core communication
- **Process Monitor** - CPU/memory tracking and adverse effects detection
- **Target Executor** - Test case execution with timeout handling
- **Oracle System** - Multi-layered failure detection (crash, hang, resource exhaustion)

### Protocol Support ✅
- **Plugin Architecture** - Single-file Python protocol definitions
- **Example Protocol** - SimpleTCP with intentional vulnerabilities for testing
- **Data Model** - Declarative message structure definition
- **State Model** - State machine representation for stateful protocols
- **Validation Oracle** - Custom response validation functions

### Testing & Examples ✅
- **Test Target** - SimpleTCP server with seeded vulnerabilities
- **Integration Tests** - Import and functionality validation
- **Example Seeds** - Pre-built test corpus for SimpleTCP

### Deployment ✅
- **Docker** - Core and Agent Dockerfiles
- **Docker Compose** - Complete multi-service orchestration
- **Makefile** - Convenience commands for dev and deployment
- **Documentation** - Quickstart guide and comprehensive README

### File Structure
```
fuzzing/
├── core/
│   ├── api/
│   │   └── server.py         # FastAPI REST API
│   ├── engine/
│   │   ├── mutators.py       # Mutation strategies
│   │   └── orchestrator.py   # Session orchestration
│   ├── corpus/
│   │   └── store.py          # Corpus & findings management
│   ├── plugins/
│   │   ├── loader.py         # Dynamic plugin loading
│   │   └── simple_tcp.py     # Example protocol
│   ├── ui/
│   │   └── index.html        # Web dashboard
│   ├── config.py             # Configuration management
│   └── models.py             # Data models (Pydantic)
├── agent/
│   ├── main.py               # Agent application
│   └── monitor.py            # Process monitoring
├── tests/
│   ├── simple_tcp_server.py  # Test target
│   └── test_imports.py       # Validation tests
├── Dockerfile                # Core container
├── Dockerfile.agent          # Agent container
├── docker-compose.yml        # Multi-service orchestration
├── Makefile                  # Dev commands
├── requirements.txt          # Dependencies
├── QUICKSTART.md            # Getting started guide
└── README.md                # This file
```

## Documentation

See:
- [Blueprint](./blueprint.md) - Architectural design
- [RFC](./rfc.md) - Engineering plan
- [Roadmap](./roadmap.md) - Implementation phases
