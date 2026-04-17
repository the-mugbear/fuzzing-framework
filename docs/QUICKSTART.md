# Quick Start Guide

**Last Updated: 2026-02-08**

Get the fuzzer running in 5 minutes.

## Prerequisites

- Python 3.11+ (for local development)
- Docker & Docker Compose (for containerized deployment)

## Option 1: Docker Deployment (Recommended)

The fastest way to get started:

```bash
# Interactive menu: Docker/Podman/local, status, stop, logs
./start.sh

# Or manually:
docker-compose up -d --build
```

This starts:
- **Core API**: The "brain" of the fuzzer, managing sessions, mutations, and serving the web UI. (http://localhost:8000)
- **Target Manager**: A service for dynamically starting/stopping test servers. (http://localhost:8001)

### Start a Test Target

Use the **Targets** page in the web UI, or start a server via the Target Manager API:

```bash
curl -X POST http://localhost:8001/targets/feature_reference_server/start
```

### Access the Web UI

Open http://localhost:8000 in your browser. You should see the fuzzer dashboard.

### Example 1: Fuzzing a Standard Protocol

1.  In the UI, select **`feature_reference`** from the protocol dropdown.
2.  The target host and port will auto-fill from running targets, or set manually to **`target-manager`** and the port shown in the Targets page.
3.  Click **Create Session**, then **Start** to begin fuzzing.

You should see test cases being executed against the test server.

### Example 2: Running an Orchestrated Fuzzing Session

This fuzzer supports multi-protocol testing, called **Orchestrated Sessions**. This is for fuzzing targets that require a handshake or other setup steps before you can fuzz the actual protocol.

The `orchestrated` plugin (in `core/plugins/examples/`) demonstrates this. It performs a handshake to get a session token, then uses that token to fuzz the target. It also uses a **heartbeat** to keep the connection alive.

1.  In the UI, select **`orchestrated`** from the protocol dropdown.
2.  Set Target Host to **`target-manager`**.
3.  Set Target Port to the port shown in the Targets page.
4.  Click **Create Session**, then **Start**.

Watch the logs (`docker-compose logs -f core`) to see the orchestration in action. You will see the `bootstrap` stage (the handshake) followed by the `fuzz_target` stage. For a deep-dive, see the **[Orchestrated Sessions Guide](ORCHESTRATED_SESSIONS_GUIDE.md)**.

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f core
docker-compose logs -f target-manager
```

For **test server logs**, use the full-screen **Log Viewer** in the web UI: go to the Targets page and click **"Open Logs"** on any running target. The viewer provides real-time streaming, log level filtering, and text search.

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
# Start the Target Manager to dynamically manage test servers
python -m target_manager --port 8001

# Then start a test target:
curl -X POST http://localhost:8001/targets/feature_reference_server/start
```

### 2b. Install & Build the Web UI

This step uses Node.js and npm to build the React-based web interface.

```bash
cd core/ui/spa
npm install
npm run build
# or run `npm run dev` for Vite + hot reload at http://localhost:5173/
```

### 3. Start the Core

In terminal 2:
```bash
python -m core.api.server
```

You should see: `INFO: Uvicorn running on http://0.0.0.0:8000`

### 4. Start the Probe (Optional)

In terminal 3:
```bash
python -m probe.main --core-url http://localhost:8000 --target-host localhost --target-port 9999
```

### 5. Access the Web UI

Open http://localhost:8000 in your browser.

## Creating Protocol Plugins

Create your plugins in `core/plugins/custom/my_protocol.py`. The plugin directory structure is:

```
core/plugins/
├── custom/      # Your plugins go here (highest priority)
├── examples/    # Reference implementations to learn from
└── standard/    # Production protocols (DNS, MQTT, etc.)
```

**For any real-world protocol, consult the full guide.** The example below is minimal:

```python
"""My custom protocol - core/plugins/custom/my_protocol.py"""

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
# ... plus state_model, validators, etc.
```

See **[Protocol Plugin Guide](PROTOCOL_PLUGIN_GUIDE.md)** for the complete reference including state machines, response handlers, and checksums. For multi-stage protocols, see **[Orchestrated Sessions Guide](ORCHESTRATED_SESSIONS_GUIDE.md)**.

Reload the Core or restart Docker to load the new plugin.

## Troubleshooting

### Core won't start
- Check port 8000 is not in use: `lsof -i :8000`
- Check logs: `docker-compose logs core`

### Probe can't connect
- Verify Core is running: `curl http://localhost:8000/api/system/health`
- Check network connectivity

### Target not responding
- Verify target is running and logs show it is listening on the correct port.
- Open the **Log Viewer** for real-time server output: click "Open Logs" on the Targets page.

## Architecture Overview

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Web UI     │      │  Core API    │      │    Probe     │
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
