# Fuzzer Quick Reference

## Quick Start

```bash
# Docker deployment (fastest)
make docker-up              # Start all services
open http://localhost:8000  # Open UI

# Local development
make install                # Install deps
make run-target            # Terminal 1: Start target
make run-core              # Terminal 2: Start Core
open http://localhost:8000  # Open UI
```

## Common Commands

```bash
# Docker
make docker-build          # Build containers
make docker-up             # Start services
make docker-down           # Stop services
make docker-logs           # View logs

# Development
make run-core              # Start Core API
make run-agent             # Start agent
make run-target            # Start test target
make test                  # Run tests

# Cleanup
make clean                 # Remove Python cache
make clean-data            # Remove corpus/crash data
```

## REST API Quick Reference

### Sessions
```bash
# Create session
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"protocol":"simple_tcp","target_host":"localhost","target_port":9999}'

# List sessions
curl http://localhost:8000/api/sessions

# Start session
curl -X POST http://localhost:8000/api/sessions/{ID}/start

# Stop session
curl -X POST http://localhost:8000/api/sessions/{ID}/stop

# Get stats
curl http://localhost:8000/api/sessions/{ID}/stats
```

### Protocols
```bash
# List plugins
curl http://localhost:8000/api/plugins

# Get plugin details
curl http://localhost:8000/api/plugins/simple_tcp
```

### Corpus
```bash
# List seeds
curl http://localhost:8000/api/corpus/seeds

# Upload seed
curl -X POST http://localhost:8000/api/corpus/seeds \
  -F "file=@myseed.bin" \
  -F 'metadata={"source":"manual"}'

# List findings
curl http://localhost:8000/api/corpus/findings

# Get finding
curl http://localhost:8000/api/corpus/findings/{ID}
```

### System
```bash
# Health check
curl http://localhost:8000/api/system/health

# Get config
curl http://localhost:8000/api/system/config

# Corpus stats
curl http://localhost:8000/api/corpus/stats
```

## Creating a Protocol Plugin

Create `core/plugins/my_protocol.py`:

```python
"""My Protocol"""
__version__ = "1.0.0"

# Define message structure
data_model = {
    "name": "MyProtocol",
    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"MYPK",
            "mutable": False  # Don't mutate
        },
        {
            "name": "length",
            "type": "uint32",
            "endian": "big",
            "is_size_field": True,
            "size_of": "payload"
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 1024
        }
    ],
    "seeds": [
        b"MYPK\x00\x00\x00\x04TEST",
        b"MYPK\x00\x00\x00\x05HELLO"
    ]
}

# Define state machine
state_model = {
    "initial_state": "INIT",
    "states": ["INIT", "AUTH", "READY"],
    "transitions": [
        {"from": "INIT", "to": "AUTH", "message_type": "AUTH"},
        {"from": "AUTH", "to": "READY", "expected_response": "OK"}
    ]
}

# Optional: Custom validation
def validate_response(response: bytes) -> bool:
    if len(response) < 4:
        return False
    if response[:4] != b"MYPK":
        return False
    return True
```

Reload plugin: `curl -X POST http://localhost:8000/api/plugins/my_protocol/reload`

## File Locations

```
Project Structure:
├── core/
│   ├── api/server.py          - REST API
│   ├── engine/
│   │   ├── mutators.py        - Mutation strategies
│   │   └── orchestrator.py    - Session management
│   ├── plugins/
│   │   └── *.py               - Protocol definitions
│   └── corpus/store.py        - Corpus management
├── agent/
│   ├── main.py                - Agent app
│   └── monitor.py             - Process monitoring
├── tests/
│   └── simple_tcp_server.py   - Test target
└── data/                      - Generated data
    ├── corpus/seeds/          - Seed files
    └── crashes/{id}/          - Crash reports
        ├── input.bin          - Reproducer
        └── report.json        - Details
```

## Environment Variables

```bash
# Core
FUZZER_API_HOST=0.0.0.0
FUZZER_API_PORT=8000
FUZZER_CORPUS_DIR=/path/to/corpus
FUZZER_CRASH_DIR=/path/to/crashes
FUZZER_MAX_CONCURRENT_TESTS=10

# Agent
FUZZER_CORE_URL=http://core:8000
FUZZER_TARGET_HOST=localhost
FUZZER_TARGET_PORT=9999
```

## Mutation Strategies

Available mutators (configured via MutationStrategy):
- `bitflip` - Random bit flipping
- `byteflip` - Random byte replacement
- `arithmetic` - Integer add/subtract
- `interesting` - Boundary values (0, -1, MAX_INT)
- `havoc` - Aggressive mutations
- `splice` - Combine seeds

## Troubleshooting

### Core won't start
```bash
# Check port
lsof -i :8000
netstat -an | grep 8000

# Check logs
docker-compose logs core
```

### Target not responding
```bash
# Test connection
echo -ne 'STCP\x00\x00\x00\x05\x01HELLO' | nc localhost 9999

# Check if running
lsof -i :9999
ps aux | grep simple_tcp_server
```

### No findings
- MVP uses simulated execution by default
- For real bugs, target must be running and accepting connections
- Check agent is connected: `docker-compose logs agent`

### Import errors
```bash
# Install dependencies
pip install -r requirements.txt

# Validate
python tests/test_imports.py
```

## Ports

- **8000** - Core API + Web UI
- **9999** - Test target (SimpleTCP)

## Useful Docker Commands

```bash
# Rebuild specific service
docker-compose build core

# Restart service
docker-compose restart core

# View logs (follow)
docker-compose logs -f core

# Execute in container
docker-compose exec core python -m core.api.server

# Remove volumes
docker-compose down -v

# Shell into container
docker-compose exec core bash
```

## Development Workflow

1. Edit code in `core/` or `agent/`
2. Plugins are hot-reloadable via API
3. For Core/Agent changes, restart service:
   ```bash
   docker-compose restart core
   # or locally:
   # Ctrl-C and re-run python -m core.api.server
   ```
4. Check logs: `make docker-logs`

## Performance Tips

- Start with small seed corpus (3-5 seeds)
- Adjust `FUZZER_MAX_CONCURRENT_TESTS` based on target capacity
- Monitor CPU/memory with `docker stats`
- Use `havoc` mutator sparingly (high computational cost)

## Getting Help

- Check `QUICKSTART.md` for detailed setup
- Read `blueprint.md` for architecture
- See `MVP_SUMMARY.md` for feature list
- View logs for debugging
