# Podman Support Guide

This fuzzing framework is fully compatible with Podman as a Docker alternative.

## Quick Start

### Prerequisites

- Podman installed: https://podman.io/getting-started/installation
- podman-compose (optional but recommended): `pip install podman-compose`

### Running with Podman

**Option 1: Using podman-compose (recommended)**
```bash
# Install podman-compose
pip install podman-compose

# Use exactly the same commands as Docker
podman-compose up -d
podman-compose build core
podman-compose logs -f core
podman-compose down
```

**Option 2: Using Podman's native compose (Podman 4.1+)**
```bash
podman compose up -d
podman compose build core
podman compose logs -f core
podman compose down
```

**Option 3: Using podman directly**
```bash
# Build image
podman build -t fuzzing-core .

# Run container
podman run -d \
  --name fuzzer-core \
  -p 8000:8000 \
  -v ./data:/app/data:Z \
  -v ./core/plugins:/app/core/plugins:Z \
  -e FUZZER_API_HOST=0.0.0.0 \
  -e FUZZER_API_PORT=8000 \
  fuzzing-core
```

## Key Differences from Docker

### 1. **Networking**

When targeting the host machine from within a Podman container:

| Podman Version | Host Address |
|----------------|--------------|
| Podman 4.1+ | `host.containers.internal` |
| Older versions | `10.0.2.2` (slirp4netns) |

Docker equivalents for comparison:
- Docker Linux: `172.17.0.1`
- Docker Mac/Windows: `host.docker.internal`

**Container-to-container networking works the same** - use service names from docker-compose.yml.

### 2. **Volume Mounts**

With SELinux enabled (Fedora, RHEL, CentOS), add `:Z` or `:z` to volume mounts:

```yaml
volumes:
  - ./data:/app/data:Z        # Private volume (recommended)
  - ./core/plugins:/app/core/plugins:z  # Shared volume
```

This is automatically handled in our docker-compose.yml when used with Podman.

### 3. **Rootless Mode**

Podman runs rootless by default (more secure):

```bash
# Check if running rootless
podman info --format "{{.Host.Security.Rootless}}"  # Should return "true"

# Containers run as your user, not root
podman ps --format "{{.ID}} {{.User}}"
```

**Port restrictions:** Rootless Podman can't bind to ports < 1024 without additional setup. Our default port 8000 works fine.

## Testing Podman Setup

### 1. Verify Installation
```bash
podman --version
podman-compose --version  # If using podman-compose
```

### 2. Build and Start
```bash
podman-compose up -d --build
```

### 3. Check Status
```bash
podman-compose ps
podman logs fuzzer-core | tail -20
```

### 4. Verify API
```bash
curl http://localhost:8000/api/system/health
```

Should return:
```json
{
  "status": "healthy",
  "active_sessions": 0,
  "total_sessions": 0,
  "corpus_seeds": 41
}
```

## Troubleshooting

### Permission Denied on Volume Mounts

**Problem:** SELinux blocking volume access

**Solution 1:** Add `:Z` to volume mounts (already in docker-compose.yml)
```yaml
volumes:
  - ./data:/app/data:Z
```

**Solution 2:** Disable SELinux enforcement (not recommended for production)
```bash
sudo setenforce 0
```

**Solution 3:** Use podman unshare
```bash
podman unshare chown -R 0:0 ./data
```

### Port Already in Use

**Problem:** Port 8000 already bound

**Solution:** Change port in docker-compose.yml
```yaml
ports:
  - "8080:8000"  # Host:Container
```

### Can't Access Host from Container

**Problem:** `host.containers.internal` not working

**Check Podman version:**
```bash
podman --version
```

**Solutions:**
- Podman 4.1+: Use `host.containers.internal`
- Older versions: Use `10.0.2.2`
- Or use `--network host` mode (less isolation):
  ```bash
  podman run --network host ...
  ```

### Slow Performance

**Problem:** Container startup/networking slower than Docker

**Solutions:**

1. **Use netavark instead of CNI** (Podman 4.0+):
   ```bash
   # Check current network backend
   podman info --format "{{.Host.NetworkBackend}}"

   # Switch to netavark if using CNI
   # Edit /etc/containers/containers.conf
   # [network]
   # network_backend = "netavark"
   ```

2. **Use pasta instead of slirp4netns** (Podman 4.4+):
   ```bash
   podman run --network pasta ...
   ```

### Image Build Failures

**Problem:** Build fails with "error building at STEP X"

**Solution:** Clear build cache
```bash
podman system prune -a --volumes
podman-compose build --no-cache
```

## Migrating from Docker

If you have existing Docker setup:

### 1. Stop Docker containers
```bash
docker-compose down
```

### 2. Use same docker-compose.yml
```bash
podman-compose up -d
```

### 3. Import existing data
```bash
# Data volumes work the same way
ls -la ./data/corpus/  # Your corpus is already there
```

### 4. Update target host addresses

If you were using Docker host addresses in your fuzzing sessions:

| Old (Docker) | New (Podman 4.1+) |
|-------------|-------------------|
| `172.17.0.1` | `host.containers.internal` |
| `host.docker.internal` | `host.containers.internal` |

## Advantages of Podman

1. **Rootless by default** - Better security, no daemon running as root
2. **Daemonless** - No background service, containers run as systemd services
3. **Compatible** - Drop-in replacement for most Docker commands
4. **Systemd integration** - Can generate systemd unit files
5. **Kubernetes YAML** - Can generate Kubernetes manifests from containers

## Docker Compatibility

The fuzzing framework uses only standard Docker features, so it's 100% compatible with both:

✅ Docker
✅ Docker Desktop
✅ Podman
✅ Podman Desktop

No code changes needed - just switch your container runtime!
