"""Target Manager — FastAPI service for managing test server lifecycles."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from target_manager.models import (
    HealthStatus,
    LogResponse,
    RunningTarget,
    ServerMeta,
    StartTargetRequest,
    TargetManagerHealth,
)
from target_manager.process_manager import ProcessManager
from target_manager.registry import discover_servers

logger = logging.getLogger("target_manager.server")

# ---- Globals wired in lifespan ----
_catalog: Dict[str, ServerMeta] = {}
_process_manager: ProcessManager | None = None

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"
PORT_RANGE = (9990, 9999)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _catalog, _process_manager

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    _catalog = discover_servers(TESTS_DIR)
    logger.info("server_catalog_loaded: %d servers", len(_catalog))

    _process_manager = ProcessManager(TESTS_DIR, port_range=PORT_RANGE)
    await _process_manager.start_health_checks()
    logger.info("target_manager_ready")

    yield

    logger.info("target_manager_shutting_down")
    await _process_manager.shutdown()


app = FastAPI(
    title="Target Manager",
    description="Dynamic test server lifecycle management",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Health ----

@app.get("/api/health", response_model=TargetManagerHealth)
async def health():
    pm = _process_manager
    return TargetManagerHealth(
        status="healthy",
        running_targets=len(pm.running_targets) if pm else 0,
        available_servers=len(_catalog),
        port_pool_available=(
            (PORT_RANGE[1] - PORT_RANGE[0] + 1) - len(pm._used_ports)
            if pm else 0
        ),
    )


# ---- Server Catalog (available scripts) ----

@app.get("/api/servers", response_model=List[ServerMeta])
async def list_servers():
    """Return all discovered test server scripts."""
    return list(_catalog.values())


@app.get("/api/servers/{script}", response_model=ServerMeta)
async def get_server(script: str):
    """Get metadata for a specific server script."""
    if script not in _catalog:
        raise HTTPException(404, f"Server script '{script}' not found in catalog")
    return _catalog[script]


# ---- Running Targets (instances) ----

@app.get("/api/targets", response_model=List[RunningTarget])
async def list_targets():
    """List all running target servers."""
    return [tp.to_running_target() for tp in _process_manager.running_targets.values()]


@app.post("/api/targets", response_model=RunningTarget, status_code=201)
async def start_target(req: StartTargetRequest):
    """Start a new target server instance."""
    if req.script not in _catalog:
        raise HTTPException(
            404,
            f"Server script '{req.script}' not found. "
            f"Available: {', '.join(_catalog.keys())}",
        )

    meta = _catalog[req.script]

    # Prevent duplicate: same script on same port
    for tp in _process_manager.running_targets.values():
        if tp.meta.script == req.script and tp.port == (req.port or meta.default_port):
            return tp.to_running_target()

    try:
        tp = await _process_manager.start_target(meta, host=req.host, port=req.port)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))

    return tp.to_running_target()


@app.get("/api/targets/{target_id}", response_model=RunningTarget)
async def get_target(target_id: str):
    """Get status of a specific running target."""
    tp = _process_manager.get_target(target_id)
    if tp is None:
        raise HTTPException(404, f"Target '{target_id}' not found")
    return tp.to_running_target()


@app.delete("/api/targets/{target_id}")
async def stop_target(target_id: str):
    """Stop a running target server."""
    ok = await _process_manager.stop_target(target_id)
    if not ok:
        raise HTTPException(404, f"Target '{target_id}' not found")
    return {"status": "stopped", "target_id": target_id}


@app.delete("/api/targets")
async def stop_all_targets():
    """Stop all running target servers."""
    count = len(_process_manager.running_targets)
    await _process_manager.stop_all()
    return {"status": "stopped", "count": count}


# ---- Logs ----

@app.get("/api/targets/{target_id}/logs", response_model=LogResponse)
async def get_target_logs(target_id: str, tail: int = 200):
    """Get recent log output from a running target."""
    tp = _process_manager.get_target(target_id)
    if tp is None:
        raise HTTPException(404, f"Target '{target_id}' not found")
    return tp.get_logs(tail=tail)


# ---- Convenience: find target by plugin ----

@app.get("/api/servers/by-plugin/{plugin_name}", response_model=List[ServerMeta])
async def servers_for_plugin(plugin_name: str):
    """Find server scripts compatible with a given protocol plugin."""
    matches = [
        meta for meta in _catalog.values()
        if plugin_name in meta.compatible_plugins
    ]
    return matches


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
