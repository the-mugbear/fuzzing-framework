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

## Execution Modes & Agents

- Sessions execute inside the Core by default. When you need to exercise a remote agent, set `execution_mode` to `agent` in the `FuzzConfig` payload while creating the session. The Core refuses to start the run unless an agent registered for the same `target_host:target_port` pair is available.
- Agents poll `/api/agents/{id}/next-case`, run inputs locally, collect CPU/memory stats (Ubuntu and Windows are supported), and POST the verdicts back to `/api/agents/{id}/result`.
- New CLI flags:
  - `--poll-interval` controls how frequently the worker checks for pending cases.
  - `--launch-cmd` lets you boot the target binary alongside the agent; the process tree is handled with process groups on Linux and `CREATE_NEW_PROCESS_GROUP` on Windows so crashes are observable.

## Mutator Selection

- Discover the built-in mutators via `GET /api/mutators` (`bitflip`, `byteflip`, `arithmetic`, `interesting`, `havoc`, `splice`).
- When calling `/api/sessions`, include `"enabled_mutators": ["bitflip", "havoc"]` to limit which strategies run. If you omit the field, the legacy boolean `mutation_strategy` flags still map to the same names.

## Declarative Field Behaviors

- Plugins can now mark individual blocks with a `behavior` stanza to perform deterministic operations before each send. Example:
  ```python
  {
      "name": "sequence",
      "type": "uint16",
      "behavior": {
          "operation": "increment",
          "initial": 0,
          "step": 1
      }
  }
  ```
- Supported operations today: `increment` (auto-increments a fixed-width integer) and `add_constant` (adds a constant before the message leaves the core/agent). Fields with behaviors must declare a fixed size so the runtime can patch the bytes.
- The UI shows these automatic operations when you pick a protocol, and the runtime keeps per-session state so sequence numbers, counters, or checksum bytes stay in sync while the rest of the payload is fuzzed.

## One-off Tests

Execute targeted payloads without spinning up a session:

```bash
curl -X POST http://localhost:8000/api/tests/execute \
  -H "Content-Type: application/json" \
  -d '{
        "protocol": "simple_tcp",
        "target_host": "localhost",
        "target_port": 9999,
        "payload": "U1RDUAAABQFIRUxMTw=="
      }'
```

The API responds with the verdict, execution time, and any bytes captured from the target. One-off execution currently runs in Core mode so responses remain synchronous.

## Logging & Troubleshooting

- Structured logs now stream to stdout **and** rotate under `logs/`. Expect `logs/core-api.log` for the FastAPI core and `logs/agent.log` for each worker host.
- When debugging agent pipelines, search for `agent_task_enqueued`, `agent_task_assigned`, and `result_submitted` lines to trace every test case end-to-end.

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

## Testing Your Protocol Implementations

### Quick Protocol Test

After creating a protocol plugin, test it works correctly:

```bash
# 1. Verify plugin loads
curl http://localhost:8000/api/plugins/your_protocol

# 2. Create a test session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"protocol": "your_protocol", "target_host": "localhost", "target_port": 9999}' \
  | jq -r '.id')

# 3. Run fuzzing for 10 seconds
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start"
sleep 10
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/stop"

# 4. Check results
curl "http://localhost:8000/api/sessions/$SESSION_ID" | jq '{
  status, total_tests, crashes, hangs, anomalies, error_message
}'
```

### Expected Results

**Successful fuzzing session:**
```json
{
  "status": "completed",
  "total_tests": 1500,
  "crashes": 2,
  "hangs": 0,
  "anomalies": 45,
  "error_message": null
}
```

**Connection issues:**
```json
{
  "status": "failed",
  "total_tests": 1,
  "crashes": 1,
  "error_message": "Connection refused to localhost:1337. Target may not be running..."
}
```

### Testing Workflow

1. **Create Protocol Plugin** - Define your protocol in `core/plugins/`
2. **Verify Plugin Loads** - Check via API: `GET /api/plugins`
3. **Test Seeds Manually** - Send seeds to your target with `nc` or Python
4. **Run Short Fuzzing Campaign** - 10-30 seconds to verify everything works
5. **Analyze Results** - Check statistics and findings
6. **Run Long Campaign** - 1+ hours for thorough testing

### Complete Testing Guide

See **[PROTOCOL_TESTING.md](./PROTOCOL_TESTING.md)** for:
- Step-by-step protocol creation
- Manual testing with seeds
- Validation strategies (structural, length, business logic, state machine)
- Debugging techniques
- Advanced testing methods
- Best practices and examples

## Documentation

See:
- **[PROTOCOL_TESTING.md](./PROTOCOL_TESTING.md)** - Complete guide for testing protocol implementations
- [QUICKSTART.md](./QUICKSTART.md) - Get started in 5 minutes
- [CHEATSHEET.md](./CHEATSHEET.md) - Quick reference commands
- [Blueprint](./blueprint.md) - Architectural design
- [RFC](./rfc.md) - Engineering plan
- [Roadmap](./roadmap.md) - Implementation phases
- [UI_ENHANCEMENTS.md](./UI_ENHANCEMENTS.md) - Web interface documentation
