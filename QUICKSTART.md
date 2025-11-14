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
- **Core API**: The "brain" of the fuzzer, which manages sessions, mutations, and serves the web UI. (http://localhost:8000)
- **Test Target**: A simple server application for you to fuzz. (localhost:9999)
- **Agent**: A "worker" process that executes test cases against the target and reports back to the Core API.

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
# or
python tests/feature_showcase_server.py --port 9001
```

You should see: `[*] SimpleTCP Server listening on 0.0.0.0:9999` (or the Feature Showcase banner if you chose the richer protocol).

### 2b. Install & Build the Web UI

This step uses Node.js and npm to build the React-based web interface. The `npm run build` command creates a production-ready version of the UI, which is then served by the Python-based Core API.

First-time setup (installs JS deps and bakes the SPA assets served by FastAPI):

```bash
cd core/ui/spa
npm install
npm run build
# or run `npm run dev` for Vite + hot reload at http://localhost:5173/ui
```

### 3. Start the Core

In terminal 2:
```bash
make run-core
# or
python -m core.api.server
```

You should see: `INFO: Uvicorn running on http://0.0.0.0:8000`

### 4. Start the Agent (Optional)

Running an agent locally is a good way to test the distributed fuzzing workflow without needing a separate machine. It helps you verify that the Core API can correctly queue work and receive results from an agent.

In terminal 3:
```bash
make run-agent
# or
python -m agent.main --core-url http://localhost:8000 --target-host localhost --target-port 9999
```

### 5. Access the Web UI

Open http://localhost:8000/ui/ in your browser (the root URL redirects here).

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

This is a very basic example. For a complete walkthrough of how to create a powerful and effective protocol plugin, including how to define state machines and response handlers, please see the full [Protocol Testing Guide](docs/PROTOCOL_TESTING.md).

## Testing Your Protocol Plugin

After creating a protocol plugin, verify it works correctly. The following sections provide a brief overview. For a comprehensive guide with more examples and advanced techniques, please see the [Protocol Testing Guide](docs/PROTOCOL_TESTING.md).

### 1. Verify Plugin Loads

```bash
# List all plugins
curl http://localhost:8000/api/plugins

# Get your protocol details
curl http://localhost:8000/api/plugins/my_protocol | jq .
```

### 2. Test Seeds Against Your Target

Create a test script `test_my_protocol.py`:

```python
#!/usr/bin/env python3
import socket
import sys
sys.path.insert(0, '.')

from core.plugin_loader import plugin_manager

TARGET_HOST = "localhost"
TARGET_PORT = 9999

protocol = plugin_manager.load_plugin("my_protocol")

for i, seed in enumerate(protocol.data_model['seeds'], 1):
    print(f"Testing seed {i}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)

    try:
        sock.connect((TARGET_HOST, TARGET_PORT))
        sock.sendall(seed)
        response = sock.recv(4096)
        print(f"  ✓ Received {len(response)} bytes")

        # Validate if validator exists
        if hasattr(protocol, 'validate_response'):
            is_valid = protocol.validate_response(response)
            print(f"  {'✓' if is_valid else '✗'} Response valid: {is_valid}")
    except Exception as e:
        print(f"  ✗ Error: {e}")
    finally:
        sock.close()
```

Run it:
```bash
python test_my_protocol.py
```

### 3. Run a Test Fuzzing Session

```bash
# Create session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "protocol": "my_protocol",
    "target_host": "localhost",
    "target_port": 9999
  }' | jq -r '.id')

# Start fuzzing for 10 seconds
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start"
sleep 10
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/stop"

# Check results
curl "http://localhost:8000/api/sessions/$SESSION_ID" | jq '{
  status, total_tests, crashes, hangs, anomalies
}'
```

Expected output:
```json
{
  "status": "completed",
  "total_tests": 1523,
  "crashes": 0,
  "hangs": 0,
  "anomalies": 0
}
```

### 4. Complete Testing Guide

For comprehensive protocol testing documentation, see:
- **[PROTOCOL_TESTING.md](./PROTOCOL_TESTING.md)** - Complete guide with advanced techniques
- Web UI → "Protocol Guide" tab - Interactive tutorial

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
- This can be normal, especially with the simple test target. The default fuzzing strategies may not be lucky enough to hit the specific vulnerabilities in the target during a short run.
- Try running the fuzzer for a longer period, or try creating a more complex protocol plugin with a wider variety of seeds.

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
