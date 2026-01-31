# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a portable, extensible fuzzing framework for proprietary network protocols. It uses a microservices architecture with three main components:

1. **Core Container** - FastAPI-based orchestrator with REST API, mutation engine, corpus store, and web UI
2. **Agent** (optional) - Lightweight monitor deployed near target systems
3. **Target** - The system under test (e.g., SimpleTCP server)

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

### Container Deployment (Recommended)

**Docker:**
```bash
# Build and start all services
docker-compose up -d

# Build specific service
docker-compose build core

# Rebuild and restart
docker-compose build core && docker-compose restart core

# View logs
docker-compose logs -f core
docker-compose logs -f target
docker-compose logs -f agent

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

# Run test target (terminal 2)
python tests/simple_tcp_server.py

# Run agent (terminal 3 - optional)
python -m agent.main --core-url http://localhost:8000 --target-host localhost --target-port 9999
```

### Testing

```bash
# Test imports
python tests/test_imports.py

# Test SimpleTCP target connectivity
echo -ne 'STCP\x00\x00\x00\x05\x01HELLO' | nc localhost 9999

# API health check
curl http://localhost:8000/api/system/health
```

### Making Changes

**For Core/Agent code changes**:
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
# Plugins are hot-reloadable - just restart Core
docker-compose restart core

# Or reload via API (if plugin already exists)
curl -X POST http://localhost:8000/api/plugins/my_protocol/reload
```

**For UI changes** (core/ui/index.html):
```bash
# Just refresh browser - no rebuild needed
# The UI is served directly from the file
```

## Architecture

### Data Flow

```
Web UI → FastAPI Server → Orchestrator → Mutation Engine → TCP Socket → Target
                ↓              ↓              ↓
           CorpusStore    Plugin Loader   (Real network I/O)
```

### Key Components

**Orchestrator** (`core/engine/orchestrator.py`):
- Main fuzzing loop in `_run_fuzzing_loop()` method
- Session lifecycle: create → start → running → stop/complete
- Executes test cases via `_execute_test_case()` which makes real TCP connections
- Handles crashes in `_handle_crash()` which saves findings to corpus

**Mutation Engine** (`core/engine/mutators.py`):
- Six mutation strategies: BitFlip, ByteFlip, Arithmetic, InterestingValues, Havoc, Splice
- Weighted probabilistic selection (see `MUTATOR_WEIGHTS`)
- Each mutator inherits from `BaseMutator` and implements `mutate(data: bytes) -> bytes`
- `MutationEngine.generate_test_case()` orchestrates the mutation pipeline

**Plugin System** (`core/plugins/loader.py`):
- Scans `core/plugins/*.py` for protocol definitions
- Plugins must define: `data_model` (message structure), `state_model` (FSM), optional `validate_response()`
- `PluginManager` caches loaded plugins in memory
- Examples:
  - `core/plugins/feature_showcase.py` - Comprehensive demonstration of all framework features (sub-byte fields, stateful fuzzing, response handlers, behaviors, validation)
  - `core/plugins/simple_tcp.py` - Minimal example for quick reference

**Corpus Store** (`core/corpus/store.py`):
- Seeds stored as `corpus/seeds/<sha256>.bin` with deduplication
- Findings stored in `data/crashes/<finding_id>/` with three files:
  - `input.bin` - Raw reproducer data
  - `report.json` - Human-readable crash report
  - `report.msgpack` - Binary format for efficiency
- **IMPORTANT**: Uses `msgpack.dump()` with `use_bin_type=True` and custom datetime handler to serialize CrashReport objects

**API Server** (`core/api/server.py`):
- FastAPI with structured logging (JSON format)
- Key endpoints: `/api/sessions`, `/api/plugins`, `/api/corpus/*`, `/api/system/health`
- Serves web UI at root `/`
- CORS enabled for browser access

### Data Models (`core/models.py`)

**Critical models**:
- `FuzzSession`: Tracks fuzzing campaign state (status, statistics, error_message)
- `TestCase`: Individual test execution with result enum
- `CrashReport`: Finding details with severity, signals, stack traces
- `TestCaseResult`: Enum for PASS, CRASH, HANG, LOGICAL_FAILURE, ANOMALY

**Key enum values**:
- `FuzzSessionStatus`: IDLE, RUNNING, PAUSED, COMPLETED, FAILED
- `TestCaseResult`: Used for oracle detection (crash vs hang vs logical bug)

### Real Network Execution

**IMPORTANT**: The orchestrator (`_execute_test_case()`) makes **real TCP socket connections** to targets:
- Uses Python's `socket` library with configurable timeout
- Sends mutated data via `sock.sendall(test_case.data)`
- Receives response with `sock.recv(4096)`
- Runs optional validator oracle: `plugin_manager.get_validator(protocol)(response)`
- Connection failures set `session.error_message` with helpful Docker networking guidance

## Creating Protocol Plugins

### Minimal Plugin Structure

```python
# core/plugins/my_protocol.py

__version__ = "1.0.0"

data_model = {
    "name": "MyProtocol",
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"MYPK", "mutable": False},
        {"name": "length", "type": "uint32", "endian": "big", "is_size_field": True, "size_of": "payload"},
        {"name": "payload", "type": "bytes", "max_size": 1024}
    ],
    # Seeds are OPTIONAL and will be auto-generated if omitted!
    # Simply omit the "seeds" key or set it to [] and the framework
    # will automatically generate baseline seeds from your data_model
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

**New Feature**: The framework can automatically generate baseline seeds from your `data_model` definition!

**How it works**:
1. **Minimal message**: Generates a seed using default values from each block
2. **Enum variants**: For fields with `values` dict, generates one seed per valid value
3. **State transitions**: For protocols with `state_model`, generates seeds that trigger each transition

**Example**:
```python
data_model = {
    "blocks": [
        {"name": "header", "type": "bytes", "size": 2, "default": b"ES"},
        {"name": "cmd", "type": "uint8", "values": {0xAA: "PING", 0xBB: "PONG"}}
    ],
    # No "seeds" key - will auto-generate 2 seeds (one for PING, one for PONG)
}
```

**When to use manual seeds**:
- Custom edge cases or known crash reproducers
- Specific test scenarios not covered by auto-generation
- Manually crafted complex multi-message sequences

**When to use auto-generation**:
- Rapid protocol prototyping
- Simple protocols with straightforward message formats
- When you want comprehensive coverage of all enum values/states

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

**Protocols with implicit length encoding** (null-terminated strings, DNS labels, etc.) should either:
- Combine variable + trailing fields into a single bytes field
- Use explicit length tracking if the wire format supports it

See `docs/PROTOCOL_PLUGIN_GUIDE.md` for detailed examples.

### Special Attributes

- `mutable: False` - Prevents fuzzer from mutating (use for magic headers)
- `is_size_field: True` - Indicates field contains length of another field
- `size_of: "fieldname"` - Links size field to data field
- `endian: "big"` or `"little"` - Byte order for integers
- `values: {}` - Dictionary of known/valid values (for documentation)

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

- **Targeting another container**: Use service name from compose file (e.g., `target`) - works for both Docker and Podman
- **"localhost" inside container**: Refers to the container itself, NOT the host
- **Targeting host machine**:
  - Docker Linux: `172.17.0.1`
  - Docker Mac/Windows: `host.docker.internal`
  - Podman 4.1+: `host.containers.internal`
  - Podman older versions: `10.0.2.2` (slirp4netns default)

Example:
```bash
# From Core container to test target container (Docker or Podman)
{"target_host": "target", "target_port": 9999}

# From Core container to host machine (Docker Linux)
{"target_host": "172.17.0.1", "target_port": 1337}

# From Core container to host machine (Podman 4.1+)
{"target_host": "host.containers.internal", "target_port": 1337}
```

The orchestrator provides helpful error messages when connection fails, including container networking guidance.

## Common Issues

### Connection Refused Errors

When `error_message` shows "Connection refused":
1. Verify target is running: `docker-compose ps` or `nc -zv localhost 9999`
2. Check Docker networking (see above)
3. Verify port matches target: SimpleTCP runs on 9999, not 8888

### Datetime Serialization Errors

If seeing "can not serialize 'datetime.datetime' object":
- CrashReport uses msgpack which requires special datetime handling
- Fix is in `core/corpus/store.py:125` with `msgpack_default()` function and `use_bin_type=True`

### Plugin Not Loading

```bash
# Check plugin file exists
ls -la core/plugins/my_protocol.py

# Check syntax
python -m py_compile core/plugins/my_protocol.py

# Check Core logs
docker-compose logs core | grep -i "plugin\|error"

# Test import directly
python -c "from core.plugins import my_protocol; print(my_protocol.data_model)"
```

### No Tests Executing (total_tests = 0)

Check session `error_message` field:
```bash
curl http://localhost:8000/api/sessions/$SESSION_ID | jq '.error_message'
```

Common causes:
- Target not reachable (connection refused)
- Wrong Docker networking configuration
- No seeds in protocol plugin

## Code Style

- **Async/await**: All orchestrator methods use asyncio
- **Structured logging**: Use `structlog.get_logger()` with key-value pairs
- **Pydantic models**: All data classes inherit from `BaseModel` (Pydantic v2)
- **Type hints**: All function signatures include type annotations
- **Error handling**: Set `session.error_message` for user-facing errors

## Web UI

Located at `core/ui/index.html`:
- Single-page app with tabbed navigation (Dashboard, Getting Started, Protocol Guide, Mutation Guide)
- Polls `/api/sessions` every 2 seconds for real-time updates
- Tooltips on all form fields and metrics
- Displays `error_message` in red error boxes when sessions fail

## Fuzzing Test Target

`tests/simple_tcp_server.py` implements a TCP server with **intentional vulnerabilities**:
- Buffer overflow: payload > 1024 bytes → crashes
- Magic crash trigger: payload == `b"CRASH"` → crashes
- Magic bytes: payload contains `\xde\xad\xbe\xef` → crashes

This validates the fuzzer can detect real bugs.

## Documentation

### Primary Documentation (docs/ directory)
- `docs/README.md` - **Documentation index** - Start here for organized access to all guides
- `docs/QUICKSTART.md` - 5-minute setup guide
- `docs/USER_GUIDE.md` - Practical fuzzing concepts and campaign strategy
- `docs/PROTOCOL_PLUGIN_GUIDE.md` - **Definitive guide** for creating, testing, and debugging protocol plugins
- `docs/PROTOCOL_SERVER_TEMPLATES.md` - Templates for test servers
- `docs/TEMPLATE_QUICK_REFERENCE.md` - Quick reference for plugin templates
- `docs/developer/` - Developer documentation (architecture, mutation engine, stateful fuzzing, etc.)

### Project Tracking & Planning
- `CHANGELOG.md` - **Record of all changes, bug fixes, and features** (update this file for every change!)
- `roadmap.md` - Future direction and planned features
- `blueprint.md` - Architectural design and technical vision
- `rfc.md` - Engineering plan and implementation phases

### Reference Guides (root level)
- `CHEATSHEET.md` - Quick reference commands for common operations

## Project Structure

```
core/
├── api/server.py          # FastAPI REST API
├── engine/
│   ├── orchestrator.py    # Main fuzzing loop, session management
│   └── mutators.py        # 6 mutation strategies
├── corpus/store.py        # Seed/findings persistence
├── plugins/
│   ├── loader.py          # Dynamic plugin loading
│   └── simple_tcp.py      # Example protocol
├── ui/index.html          # Web dashboard
├── config.py              # Settings (from env vars)
└── models.py              # Pydantic data models

agent/
├── main.py                # Agent application
└── monitor.py             # Process monitoring

tests/
├── simple_tcp_server.py   # Test target with bugs
└── test_imports.py        # Validation tests
```

## Environment Variables

**Core**:
- `FUZZER_API_HOST` - Default: 0.0.0.0
- `FUZZER_API_PORT` - Default: 8000
- `FUZZER_CORPUS_DIR` - Default: /app/data/corpus
- `FUZZER_MAX_CONCURRENT_TESTS` - Default: 10

**Agent**:
- `FUZZER_CORE_URL` - Core API URL (e.g., http://core:8000)
- `FUZZER_TARGET_HOST` - Target hostname
- `FUZZER_TARGET_PORT` - Target port
