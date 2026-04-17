# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a portable, extensible fuzzing framework for proprietary network protocols. It uses a microservices architecture with three main components:

1. **Core Container** - FastAPI-based orchestrator with REST API, mutation engine, corpus store, and React SPA
2. **Target Manager** - Dynamic test server lifecycle management (start/stop servers via API)
3. **Probe** (optional) - Lightweight monitor deployed near target systems

The framework implements intelligent mutation-based fuzzing with a plugin system for protocol definitions.

## Recording Changes

**IMPORTANT**: All code changes, bug fixes, new features, and modifications must be documented in `CHANGELOG.md`.

### Changelog Guidelines

- **Format**: Follow [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) conventions
- **Categories**: Added, Changed, Fixed, Deprecated, Removed, Security, Verified
- **Timestamps**: Include date (YYYY-MM-DD) for all entries
- **Detail Level**: Include file paths, line numbers, and brief explanation of what was changed and why
- **Testing**: Add testing recommendations for significant changes
- **Configuration**: Document new environment variables or config options

### When to Update Changelog

Update `CHANGELOG.md` whenever you:
- Implement a new feature or component
- Fix a bug (especially critical or high-priority bugs)
- Modify existing behavior
- Add or change configuration options
- Refactor significant code sections
- Verify or document existing functionality
- Complete a work session with multiple changes

### Changelog Entry Template

```markdown
### Fixed - YYYY-MM-DD

- **Brief description** (`file/path.py:line-range`)
  - What was broken
  - How it was fixed
  - Impact of the fix
  - Related changes in other files
```

**Example**:
```markdown
### Fixed - 2026-01-06

- **Fixed runtime helper rebuild on session load** (`core/engine/orchestrator.py:93`)
  - Changed `self.plugin_manager` to `plugin_manager` (module-level import)
  - Behavior processors and response planners now correctly rebuilt on restart
  - Without this fix, session loading failed with AttributeError
```

## Building and Running

### Startup Script (Quickest)

```bash
# Interactive menu: Docker/Podman/local, status, stop, logs
./start.sh
```

### Container Deployment (Recommended)

**Docker:**
```bash
# Build and start all services (core + target-manager)
docker-compose up -d --build

# Build specific service
docker-compose build core

# Rebuild and restart
docker-compose build core && docker-compose restart core

# View logs
docker-compose logs -f core
docker-compose logs -f target-manager

# Stop everything
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

**Podman:**
```bash
# Install podman-compose if needed
pip install podman-compose

# Use same commands with podman-compose
podman-compose up -d
podman-compose build core
podman-compose logs -f core
podman-compose down

# Or use Podman's native compose (Podman 4.1+)
podman compose up -d
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run Core API (terminal 1)
python -m core.api.server

# Start a test target via Target Manager (terminal 2)
python -m target_manager --port 8001
# Then use the Targets page in the UI to start servers, or:
curl -X POST http://localhost:8001/targets/feature_reference_server/start

# Build the Web UI (terminal 3, for development)
cd core/ui/spa && npm install && npm run build
# Or for hot-reload: npm run dev

# Run probe (terminal 4 — optional)
python -m probe.main --core-url http://localhost:8000 --target-host localhost --target-port 9999
```

### Testing

```bash
# Run all tests
pytest tests/ -v

# Test imports
python tests/test_imports.py

# API health check
curl http://localhost:8000/api/system/health
```

### Making Changes

**For Core code changes**:
```bash
# Rebuild the container
docker-compose build core

# Recreate and restart (required to pick up code changes)
docker-compose down && docker-compose up -d

# Or rebuild and recreate in one step
docker-compose up -d --build core
```

**For protocol plugins**:
```bash
# Plugins are hot-reloadable — just restart Core
docker-compose restart core

# Or reload via API (if plugin already exists)
curl -X POST http://localhost:8000/api/plugins/my_protocol/reload
```

**For UI changes** (`core/ui/spa/`):
```bash
# Development: run Vite dev server with hot reload
cd core/ui/spa && npm run dev

# Production: rebuild and restart Core
cd core/ui/spa && npm run build
docker-compose restart core
```

## Architecture

### Data Flow

```
React SPA → FastAPI Server → Orchestrator → Mutation Engine → TCP Socket → Target
                 ↓              ↓              ↓
            CorpusStore    Plugin Loader   (Real network I/O)
```

### Key Components

**Orchestrator** (`core/engine/orchestrator.py`):
- Facade delegating to decomposed components (SessionManager, FuzzingLoopCoordinator, TestExecutor, etc.)
- Session lifecycle: create → start → running → stop/complete
- Supports both simple and orchestrated (multi-stage) sessions
- Handles crashes via `crash_handler.py` which saves findings to corpus

**Mutation Engine** (`core/engine/mutators.py`, `structure_mutators.py`):
- Byte-level mutations: BitFlip, ByteFlip, Arithmetic, InterestingValues, Havoc, Splice
- Structure-aware mutations that respect protocol grammar
- Weighted probabilistic selection (see `MUTATOR_WEIGHTS`)
- Each mutator inherits from `BaseMutator` and implements `mutate(data: bytes) -> bytes`

**Plugin System** (`core/plugin_loader.py`):
- Scans `core/plugins/{custom,examples,standard}/` for protocol definitions
- Priority: custom > examples > standard (custom overrides same-named plugins)
- Plugins must define: `data_model` (message structure), `state_model` (FSM), optional `validate_response()`
- `PluginManager` caches loaded plugins in memory
- Examples:
  - `core/plugins/examples/feature_reference.py` — Comprehensive demonstration of all framework features
  - `core/plugins/examples/minimal_tcp.py` — Minimal TCP example for quick reference
  - `core/plugins/examples/orchestrated.py` — Multi-stage orchestrated session example

**Corpus Store** (`core/corpus/store.py`):
- Seeds stored as `corpus/seeds/<sha256>.bin` with deduplication
- Findings stored in `data/crashes/<finding_id>/` with three files:
  - `input.bin` — Raw reproducer data
  - `report.json` — Human-readable crash report
  - `report.msgpack` — Binary format for efficiency
- **IMPORTANT**: Uses `msgpack.dump()` with `use_bin_type=True` and custom datetime handler to serialize CrashReport objects

**API Server** (`core/api/server.py`):
- FastAPI with structured logging (JSON format)
- Key endpoints: `/api/sessions`, `/api/plugins`, `/api/corpus/*`, `/api/system/health`
- Serves React SPA at root `/`
- CORS enabled for browser access

**Target Manager** (`target_manager/`):
- Separate FastAPI service on port 8001
- Discovers test servers with `__server_meta__` dicts
- Start/stop/health-check servers via REST API
- UI integration: Targets page in the SPA

### Data Models (`core/models.py`)

**Critical models**:
- `FuzzSession`: Tracks fuzzing campaign state (status, statistics, error_message)
- `TestCase`: Individual test execution with result enum
- `CrashReport`: Finding details with severity, signals, stack traces
- `TestCaseResult`: Enum for PASS, CRASH, HANG, LOGICAL_FAILURE, ANOMALY
- `ProtocolPlugin`: Plugin metadata including `target_servers` for UI auto-fill

**Key enum values**:
- `FuzzSessionStatus`: IDLE, RUNNING, PAUSED, COMPLETED, FAILED
- `TestCaseResult`: Used for oracle detection (crash vs hang vs logical bug)

### Real Network Execution

**IMPORTANT**: The orchestrator makes **real TCP socket connections** to targets:
- Uses Python's `socket` library with configurable timeout
- Sends mutated data via `sock.sendall(test_case.data)`
- Receives response with `sock.recv(4096)`
- Runs optional validator oracle: `plugin_manager.get_validator(protocol)(response)`
- Connection failures set `session.error_message` with helpful Docker networking guidance

## Creating Protocol Plugins

### Plugin Directory Structure

```
core/plugins/
├── custom/      # Your plugins (highest priority, .gitignored)
├── examples/    # Reference implementations to learn from
└── standard/    # Production protocols (DNS, MQTT, Modbus, etc.)
```

### Minimal Plugin Structure

```python
# core/plugins/custom/my_protocol.py

__version__ = "1.0.0"

data_model = {
    "name": "MyProtocol",
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"MYPK", "mutable": False},
        {"name": "length", "type": "uint32", "endian": "big", "is_size_field": True, "size_of": "payload"},
        {"name": "payload", "type": "bytes", "max_size": 1024}
    ],
    # Seeds are OPTIONAL — auto-generated from data_model if omitted
}

state_model = {
    "initial_state": "INIT",
    "states": ["INIT", "READY"],
    "transitions": []
}

def validate_response(response: bytes) -> bool:
    """Optional specification oracle - checks for logical bugs"""
    if len(response) < 4:
        return False
    if response[:4] != b"MYPK":
        return False
    return True
```

### Automatic Seed Generation

The framework automatically generates baseline seeds from your `data_model` definition:

1. **Minimal message**: Generates a seed using default values from each block
2. **Enum variants**: For fields with `values` dict, generates one seed per valid value
3. **State transitions**: For protocols with `state_model`, generates seeds that trigger each transition

### Field Types

- `bytes`: Raw byte array (needs `size` or `max_size`)
- `uint8`, `uint16`, `uint32`, `uint64`: Unsigned integers
- `int8`, `int16`, `int32`, `int64`: Signed integers
- `string`: UTF-8 text (specify `encoding`)

### Variable-Length Field Requirements

**IMPORTANT**: Variable-length fields (`max_size` without fixed `size`) must either:
1. Have an explicit length field linked via `is_size_field`/`size_of`, OR
2. Be the **last field** in the message (parser reads remaining bytes)

Without this, the parser consumes all remaining bytes into the variable field, breaking subsequent fields.

See `docs/PROTOCOL_PLUGIN_GUIDE.md` for detailed examples.

### Special Attributes

- `mutable: False` — Prevents fuzzer from mutating (use for magic headers)
- `is_size_field: True` — Indicates field contains length of another field
- `size_of: "fieldname"` — Links size field to data field
- `endian: "big"` or `"little"` — Byte order for integers
- `values: {}` — Dictionary of known/valid values (for documentation)

### Testing Protocol Plugins

```bash
# 1. Verify plugin loads
curl http://localhost:8000/api/plugins/my_protocol

# 2. Test seed manually
echo -ne 'MYPK\x00\x00\x00\x04TEST' | nc localhost 9999

# 3. Create and run test session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"protocol":"my_protocol","target_host":"localhost","target_port":9999}' \
  | jq -r '.id')

curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start"
sleep 10
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/stop"

# 4. Check results
curl "http://localhost:8000/api/sessions/$SESSION_ID" | jq '{status, total_tests, crashes, hangs, anomalies, error_message}'
```

See `docs/PROTOCOL_PLUGIN_GUIDE.md` for comprehensive guide on creating and testing protocol plugins.

## Container Networking

**IMPORTANT for testing**: When fuzzing from containers:

- **Targeting a dynamic target**: Start server via Target Manager, then use `target-manager` as hostname with the assigned port
- **"localhost" inside container**: Refers to the container itself, NOT the host
- **Targeting host machine**:
  - Docker Linux: `172.17.0.1`
  - Docker Mac/Windows: `host.docker.internal`
  - Podman 4.1+: `host.containers.internal`
  - Podman older versions: `10.0.2.2` (slirp4netns default)

Example:
```bash
# From Core container to a target started via Target Manager
{"target_host": "target-manager", "target_port": 9999}

# From Core container to host machine (Docker Linux)
{"target_host": "172.17.0.1", "target_port": 1337}

# From Core container to host machine (Podman 4.1+)
{"target_host": "host.containers.internal", "target_port": 1337}
```

The orchestrator provides helpful error messages when connection fails, including container networking guidance.

## Common Issues

### Connection Refused Errors

When `error_message` shows "Connection refused":
1. Verify target is running: `docker-compose ps` or check the Targets page in the UI
2. Check Docker networking (see above)
3. Verify port matches target: use the port shown in the Targets page

### Datetime Serialization Errors

If seeing "can not serialize 'datetime.datetime' object":
- CrashReport uses msgpack which requires special datetime handling
- Fix is in `core/corpus/store.py` with `msgpack_default()` function and `use_bin_type=True`

### Plugin Not Loading

```bash
# Check plugin file exists
ls -la core/plugins/custom/my_protocol.py

# Check syntax
python -m py_compile core/plugins/custom/my_protocol.py

# Check Core logs
docker-compose logs core | grep -i "plugin\|error"
```

### No Tests Executing (total_tests = 0)

Check session `error_message` field:
```bash
curl http://localhost:8000/api/sessions/$SESSION_ID | jq '.error_message'
```

Common causes:
- Target not reachable (connection refused)
- Wrong Docker networking configuration
- No seeds in protocol plugin (seeds are auto-generated, so this is rare)

## Code Style

- **Async/await**: All orchestrator methods use asyncio
- **Structured logging**: Use `structlog.get_logger()` with key-value pairs
- **Pydantic models**: All data classes inherit from `BaseModel` (Pydantic v2)
- **Type hints**: All function signatures include type annotations
- **Error handling**: Set `session.error_message` for user-facing errors

## Web UI

Located at `core/ui/spa/` — a React 18 + TypeScript + Vite SPA:
- **Dashboard**: Session management, real-time stats, create/start/stop fuzzing sessions
- **Targets**: Start/stop test servers dynamically via Target Manager API
- **Documentation Hub**: Browse all docs from within the UI
- Polls `/api/sessions` every 2 seconds for real-time updates
- Auto-fills target host/port from running targets

## Test Servers

Test servers live in `tests/` and are discovered by the Target Manager via `__server_meta__` dicts:

| Server | Protocol | Purpose |
|--------|----------|---------|
| `simple_tcp_server.py` | `minimal_tcp` | Basic TCP with intentional crash triggers |
| `feature_reference_server.py` | `feature_reference` | Full-featured: state machine, orchestration, vulnerabilities |
| `template_tcp_server.py` | *(template)* | Customizable TCP server template |
| `template_udp_server.py` | *(template)* | Customizable UDP server template |
| `udp_server.py` | `minimal_udp` | Basic UDP echo server |

## Documentation

### Primary Documentation (docs/ directory)
- `docs/README.md` — **Documentation index** — Start here for organized access to all guides
- `docs/QUICKSTART.md` — 5-minute setup guide
- `docs/USER_GUIDE.md` — Practical fuzzing concepts and campaign strategy
- `docs/PROTOCOL_PLUGIN_GUIDE.md` — **Definitive guide** for creating, testing, and debugging protocol plugins
- `docs/PROTOCOL_SERVER_TEMPLATES.md` — Templates and guide for test servers
- `docs/TEMPLATE_QUICK_REFERENCE.md` — Quick reference for server template patterns
- `docs/developer/` — Developer documentation (architecture, mutation engine, stateful fuzzing, etc.)

### Project Tracking & Planning
- `CHANGELOG.md` — **Record of all changes, bug fixes, and features** (update this file for every change!)
- `blueprint.md` — Architectural design vision (annotated: implemented vs. aspirational)

### Reference Guides (root level)
- `CHEATSHEET.md` — Quick reference commands for common operations

## Project Structure

```
core/
├── api/
│   ├── server.py              # FastAPI REST API
│   └── routes/                # Organized route modules
├── engine/
│   ├── orchestrator.py        # Facade coordinating all components
│   ├── session_manager.py     # Session CRUD and lifecycle
│   ├── fuzzing_loop.py        # Main fuzzing iteration loop
│   ├── test_executor.py       # Transport and execution
│   ├── state_navigator.py     # State machine navigation
│   ├── mutators.py            # Byte-level mutation strategies
│   ├── structure_mutators.py  # Structure-aware mutations
│   ├── protocol_parser.py     # Bytes ↔ fields bidirectional parser
│   ├── stage_runner.py        # Orchestrated session stages
│   ├── heartbeat_scheduler.py # Keep-alive for persistent connections
│   ├── connection_manager.py  # Thread-safe socket management
│   ├── protocol_context.py    # Shared state between stages
│   ├── crash_handler.py       # Crash detection and reporting
│   ├── probe_dispatcher.py    # Remote probe coordination
│   └── ...                    # Additional engine components
├── corpus/store.py            # Seed/findings persistence
├── plugins/
│   ├── custom/                # User plugins (highest priority)
│   ├── examples/              # Reference implementations
│   │   ├── feature_reference.py
│   │   ├── minimal_tcp.py
│   │   ├── minimal_udp.py
│   │   ├── orchestrated.py
│   │   └── ...
│   └── standard/              # Production protocols (DNS, MQTT, etc.)
├── plugin_loader.py           # Dynamic plugin loading
├── protocol_behavior.py       # Declarative field behaviors
├── ui/spa/                    # React 18 + TypeScript + Vite SPA
├── config.py                  # Settings (from env vars)
└── models.py                  # Pydantic data models

target_manager/
├── server.py                  # FastAPI on :8001
├── registry.py                # Server discovery via __server_meta__
├── process_manager.py         # Process lifecycle management
└── models.py                  # Target manager data models

probe/
├── main.py                    # Probe application
└── monitor.py                 # Process monitoring

tests/
├── simple_tcp_server.py       # Basic test target with crash triggers
├── feature_reference_server.py# Full-featured test target
├── template_tcp_server.py     # TCP server template
├── template_udp_server.py     # UDP server template
└── test_*.py                  # pytest test files
```

## Environment Variables

**Core**:
- `FUZZER_API_HOST` — Default: 0.0.0.0
- `FUZZER_API_PORT` — Default: 8000
- `FUZZER_CORPUS_DIR` — Default: /app/data/corpus
- `FUZZER_MAX_CONCURRENT_TESTS` — Default: 10

**Probe**:
- `FUZZER_CORE_URL` — Core API URL (e.g., http://core:8000)
- `FUZZER_TARGET_HOST` — Target hostname
- `FUZZER_TARGET_PORT` — Target port
