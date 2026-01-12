"""FastAPI application entrypoint for the Core API."""
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

app = FastAPI(
    title="Proprietary Protocol Fuzzer",
    description="Portable, extensible fuzzing framework for proprietary network protocols",
    version="0.1.0",
)


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("application_startup")


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shutdown services."""
    from core.api.deps import get_orchestrator

    orchestrator = get_orchestrator()
    await orchestrator.history_store.shutdown()
    logger.info("application_shutdown")

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
