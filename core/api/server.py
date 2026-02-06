"""
FastAPI Application - Core API server entrypoint.

This module provides the main FastAPI application that serves the
fuzzer's REST API and web UI.

Component Overview:
-------------------
The server provides:
- REST API endpoints for session management
- WebSocket support for real-time updates
- Static file serving for documentation and UI
- CORS configuration for browser access

Key Features:
------------
1. API Routes:
   - /api/sessions: Session CRUD and control
   - /api/corpus: Seed and finding management
   - /api/plugins: Protocol plugin access
   - /api/system: Health and metrics

2. Static Mounts:
   - /docs: Developer documentation
   - /ui: Web dashboard

3. Lifespan Management:
   - Startup: Initialize orchestrator, start background tasks
   - Shutdown: Flush pending data, clean shutdown

4. CORS Configuration:
   - Configurable via environment variables
   - Permissive by default for local development

Configuration:
-------------
- FUZZER_API_HOST: Bind address (default: 0.0.0.0)
- FUZZER_API_PORT: Port (default: 8000)
- FUZZER_CORS_ENABLED: Enable CORS (default: true)
- FUZZER_CORS_ORIGINS: Allowed origins (default: ["*"])

Usage:
-----
    # Run directly
    python -m core.api.server

    # Or with uvicorn
    uvicorn core.api.server:app --host 0.0.0.0 --port 8000

See Also:
--------
- core/api/routes/*.py - Individual route modules
- core/api/deps.py - Dependency injection
- docs/QUICKSTART.md - Getting started guide
"""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from core.api.routes import ROUTERS
from core.config import settings
from core.logging import setup_logging

setup_logging("core-api")
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management.

    Replaces deprecated @app.on_event("startup") and @app.on_event("shutdown")
    with the modern lifespan context manager pattern.
    """
    # Startup
    from core.api.deps import get_orchestrator

    orchestrator = get_orchestrator()
    orchestrator.history_store.start_background_writer()
    logger.info("application_startup")

    yield

    # Shutdown
    orchestrator = get_orchestrator()
    await orchestrator.history_store.shutdown()
    logger.info("application_shutdown")


app = FastAPI(
    title="Proprietary Protocol Fuzzer",
    description="Portable, extensible fuzzing framework for proprietary network protocols",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS (configurable via FUZZER_CORS_ENABLED and FUZZER_CORS_ORIGINS)
if settings.cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("cors_enabled", origins=settings.cors_origins)

# Static mounts
for mount_path, directory in (
    ("/docs", settings.project_root / "docs"),
    ("/guides", settings.project_root / "core" / "ui" / "guides"),
):
    if directory.exists():
        app.mount(mount_path, StaticFiles(directory=directory), name=mount_path.strip("/"))

spa_dist = settings.project_root / "core" / "ui" / "spa" / "dist"
if spa_dist.exists():
    app.mount("/ui", StaticFiles(directory=spa_dist, html=True), name="spa")


@app.get("/")
async def root():
    index_path = spa_dist / "index.html"
    if index_path.exists():
        return RedirectResponse(url="/ui/")
    return {
        "service": "Proprietary Protocol Fuzzer",
        "version": "0.1.0",
        "status": "operational",
        "message": "UI assets not found. Run `make ui-build` to generate the SPA.",
    }


for router in ROUTERS:
    app.include_router(router)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    logger.info(
        "starting_fuzzer_core",
        host=settings.api_host,
        port=settings.api_port,
    )
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")
