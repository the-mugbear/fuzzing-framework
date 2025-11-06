# Quick Start Guide

Get the fuzzer running in 5 minutes.

## Prerequisites

- Python 3.11+ (for local development)
- Docker & Docker Compose (for containerized deployment)

## Option 1: Docker Deployment (Recommended)

The fastest way to get started:

```bash
# Build and start all services
make docker-up

# Or manually:
docker-compose up -d
```

This starts:
- **Core API** at http://localhost:8000 (includes Web UI)
- **Test Target** at localhost:9999
- **Agent** (connecting to Core and Target)

### Access the Web UI

Open http://localhost:8000 in your browser. You should see the fuzzer dashboard.

### Create and Run a Fuzzing Session

1. In the UI, select "simple_tcp" from the protocol dropdown
2. Set target to "target" (Docker service name) or "localhost"
3. Port: 9999
4. Click "Create Session"
5. Click "Start" to begin fuzzing

You should see test cases being executed and statistics updating in real-time.

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f core
docker-compose logs -f target
docker-compose logs -f agent
```

### Stop Everything

```bash
make docker-down
# or
docker-compose down
```

## Option 2: Local Development

For development and testing without Docker:

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
make install
# or
pip install -r requirements.txt
```

### 2. Start the Test Target

In terminal 1:
```bash
make run-target
# or
python tests/simple_tcp_server.py
```

You should see: `[*] SimpleTCP Server listening on 0.0.0.0:9999`

### 3. Start the Core

In terminal 2:
```bash
make run-core
# or
python -m core.api.server
```

You should see: `INFO: Uvicorn running on http://0.0.0.0:8000`

### 4. Start the Agent (Optional)

In terminal 3:
```bash
make run-agent
# or
python -m agent.main --core-url http://localhost:8000 --target-host localhost --target-port 9999
```

### 5. Access the Web UI

Open http://localhost:8000 in your browser.

## Testing the Setup

### Test the API

```bash
# Check health
curl http://localhost:8000/api/system/health

# List protocols
curl http://localhost:8000/api/plugins

# Get protocol details
curl http://localhost:8000/api/plugins/simple_tcp
```

### Test the Target

```bash
make test-target
# or manually:
echo -ne 'STCP\x00\x00\x00\x05\x01HELLO' | nc localhost 9999
```

You should receive a response starting with "STCP".

### Create a Session via API

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "protocol": "simple_tcp",
    "target_host": "localhost",
    "target_port": 9999
  }'
```

This returns a session ID. Use it to start fuzzing:

```bash
curl -X POST http://localhost:8000/api/sessions/{SESSION_ID}/start
```

## Understanding the Results

### Session Statistics

Check stats:
```bash
curl http://localhost:8000/api/sessions/{SESSION_ID}/stats
```

Returns:
- `total_tests`: Number of test cases executed
- `crashes`: Detected crashes
- `hangs`: Timeout/hang conditions
- `anomalies`: Behavioral anomalies

### Findings

List all findings:
```bash
curl http://localhost:8000/api/corpus/findings
```

Get specific finding:
```bash
curl http://localhost:8000/api/corpus/findings/{FINDING_ID}
```

Findings are stored in `data/crashes/{FINDING_ID}/`:
- `input.bin` - The input that triggered the finding
- `report.json` - Full crash report with metadata
- `report.msgpack` - Binary format for efficient storage

## Next Steps

1. **Create Custom Protocol**: See [Creating Protocol Plugins](#creating-protocol-plugins)
2. **Upload Seeds**: Add your own seed corpus via the API or UI
3. **Analyze Findings**: Review crash reports and reproducers
4. **Scale Up**: Run multiple agents for distributed fuzzing

## Creating Protocol Plugins

Create a new file in `core/plugins/my_protocol.py`:

```python
"""My custom protocol"""

__version__ = "1.0.0"

data_model = {
    "name": "MyProtocol",
    "blocks": [
        {"name": "header", "type": "bytes", "size": 4, "default": b"MYPK"},
        {"name": "length", "type": "uint32", "endian": "big"},
        {"name": "payload", "type": "bytes", "max_size": 1024},
    ],
    "seeds": [
        b"MYPK\x00\x00\x00\x04TEST",
    ]
}

state_model = {
    "initial_state": "INIT",
    "states": ["INIT", "READY"],
    "transitions": []
}

def validate_response(response: bytes) -> bool:
    """Optional: Custom validation logic"""
    return len(response) >= 4
```

Reload the Core or restart Docker to load the new plugin.

## Troubleshooting

### Core won't start
- Check port 8000 is not in use: `lsof -i :8000`
- Check logs: `docker-compose logs core`

### Agent can't connect
- Verify Core is running: `curl http://localhost:8000/api/system/health`
- Check network connectivity

### Target not responding
- Verify target is running: `make test-target`
- Check port 9999: `lsof -i :9999`

### No findings being generated
- This is expected with the test target - it has intentional vulnerabilities but the MVP's simulated execution may not always trigger them
- Try creating actual network connections to the target

## Architecture Overview

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Web UI     │      │  Core API    │      │    Agent     │
│  (Browser)   │─────▶│  (FastAPI)   │◀────▶│  (Monitor)   │
└──────────────┘      └──────────────┘      └──────────────┘
                             │                      │
                             │                      │
                             ▼                      ▼
                      ┌──────────────┐      ┌──────────────┐
                      │   Plugins    │      │    Target    │
                      │   Corpus     │      │   (Fuzz Me)  │
                      └──────────────┘      └──────────────┘
```

## Support

- GitHub Issues: https://github.com/yourusername/fuzzer
- Documentation: See `blueprint.md`, `rfc.md`, `roadmap.md`
