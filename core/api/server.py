"""
FastAPI server for the fuzzer Core

Provides REST API for:
- Session management
- Protocol plugin management
- Corpus management
- Agent communication
- Results and findings
"""
from typing import List, Optional

import structlog
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from core.agents.manager import agent_manager
from core.config import settings
from core.logging import setup_logging
from core.corpus.store import CorpusStore
from core.engine.mutators import MutationEngine
from core.engine.orchestrator import orchestrator
from core.models import (
    AgentTestResult,
    AgentWorkItem,
    FuzzConfig,
    FuzzSession,
    OneOffTestRequest,
    OneOffTestResult,
    ProtocolPlugin,
)
from core.plugin_loader import plugin_manager

setup_logging("core-api")
logger = structlog.get_logger()

# Create FastAPI app
app = FastAPI(
    title="Proprietary Protocol Fuzzer",
    description="Portable, extensible fuzzing framework for proprietary network protocols",
    version="0.1.0",
)

# CORS middleware for web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

corpus_store = CorpusStore()


docs_path = settings.project_root / "docs"
if docs_path.exists():
    app.mount("/docs", StaticFiles(directory=docs_path), name="docs")

guides_path = settings.project_root / "core" / "ui" / "guides"
if guides_path.exists():
    app.mount("/guides", StaticFiles(directory=guides_path), name="guides")


@app.get("/")
async def root():
    """Serve the web UI"""
    ui_path = settings.project_root / "core" / "ui" / "index.html"
    if ui_path.exists():
        return FileResponse(ui_path)
    return {
        "service": "Proprietary Protocol Fuzzer",
        "version": "0.1.0",
        "status": "operational",
    }


# ========== Protocol Plugin Endpoints ==========


@app.get("/api/plugins", response_model=List[str])
async def list_plugins():
    """List all available protocol plugins"""
    try:
        plugins = plugin_manager.discover_plugins()
        return plugins
    except Exception as e:
        logger.error("failed_to_list_plugins", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/plugins/{plugin_name}", response_model=ProtocolPlugin)
async def get_plugin(plugin_name: str):
    """Get details of a specific protocol plugin"""
    try:
        plugin = plugin_manager.load_plugin(plugin_name)
        return plugin
    except Exception as e:
        logger.error("failed_to_load_plugin", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_name}")


@app.post("/api/plugins/{plugin_name}/reload", response_model=ProtocolPlugin)
async def reload_plugin(plugin_name: str):
    """Reload a protocol plugin (useful for development)"""
    try:
        plugin = plugin_manager.reload_plugin(plugin_name)
        logger.info("plugin_reloaded", plugin=plugin_name)
        return plugin
    except Exception as e:
        logger.error("failed_to_reload_plugin", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mutators")
async def list_mutators():
    """Expose available mutators for the UI"""
    return {"mutators": MutationEngine.available_mutators()}


# ========== Session Management Endpoints ==========


@app.post("/api/sessions", response_model=FuzzSession)
async def create_session(config: FuzzConfig):
    """Create a new fuzzing session"""
    try:
        session = await orchestrator.create_session(config)
        logger.info("session_created_via_api", session_id=session.id)
        return session
    except Exception as e:
        logger.error("failed_to_create_session", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions", response_model=List[FuzzSession])
async def list_sessions():
    """List all fuzzing sessions"""
    return orchestrator.list_sessions()


@app.get("/api/sessions/{session_id}", response_model=FuzzSession)
async def get_session(session_id: str):
    """Get details of a specific session"""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/api/sessions/{session_id}/start")
async def start_session(session_id: str):
    """Start a fuzzing session"""
    success = await orchestrator.start_session(session_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start session")
    return {"status": "started", "session_id": session_id}


@app.post("/api/sessions/{session_id}/stop")
async def stop_session(session_id: str):
    """Stop a fuzzing session"""
    success = await orchestrator.stop_session(session_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to stop session")
    return {"status": "stopped", "session_id": session_id}


@app.get("/api/sessions/{session_id}/stats")
async def get_session_stats(session_id: str):
    """Get session statistics"""
    stats = orchestrator.get_session_stats(session_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Session not found")
    return stats


# ========== Ad-hoc Testing ==========


@app.post("/api/tests/execute", response_model=OneOffTestResult)
async def execute_test(request: OneOffTestRequest):
    """Execute a single test case without creating a session"""
    try:
        result = await orchestrator.execute_one_off(request)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ========== Corpus Management Endpoints ==========


@app.get("/api/corpus/seeds")
async def list_seeds():
    """List all seed IDs in the corpus"""
    return {"seed_ids": corpus_store.get_seed_ids()}


@app.post("/api/corpus/seeds")
async def upload_seed(file: UploadFile = File(...), metadata: Optional[str] = None):
    """Upload a new seed to the corpus"""
    try:
        data = await file.read()
        import json

        meta = json.loads(metadata) if metadata else {}
        meta["filename"] = file.filename

        seed_id = corpus_store.add_seed(data, metadata=meta)
        return {"seed_id": seed_id, "size": len(data)}
    except Exception as e:
        logger.error("failed_to_upload_seed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/corpus/stats")
async def get_corpus_stats():
    """Get corpus statistics"""
    return corpus_store.get_corpus_stats()


@app.get("/api/corpus/findings")
async def list_findings(session_id: Optional[str] = None):
    """List all findings (crashes, hangs, anomalies)"""
    findings = corpus_store.list_findings(session_id)
    return {"findings": findings, "count": len(findings)}


@app.get("/api/corpus/findings/{finding_id}")
async def get_finding(finding_id: str):
    """Get details of a specific finding"""
    result = corpus_store.load_finding(finding_id)
    if not result:
        raise HTTPException(status_code=404, detail="Finding not found")

    crash_report, test_case_data = result
    return {
        "report": crash_report,
        "reproducer_size": len(test_case_data),
        "reproducer_sha256": crash_report.id,
    }


# ========== Agent Communication Endpoints ==========


@app.post("/api/agents/register")
async def register_agent(agent_info: dict):
    """Register a new agent"""
    required_fields = {"agent_id", "hostname", "target_host", "target_port"}
    missing = [field for field in required_fields if field not in agent_info]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {', '.join(missing)}")

    status = agent_manager.register_agent(
        agent_id=agent_info["agent_id"],
        hostname=agent_info["hostname"],
        target_host=agent_info["target_host"],
        target_port=int(agent_info["target_port"]),
    )
    return status


@app.post("/api/agents/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: str, status: dict):
    """Agent heartbeat and status update"""
    updated = agent_manager.heartbeat(
        agent_id,
        cpu_usage=status.get("cpu_usage", 0.0),
        memory_usage_mb=status.get("memory_usage_mb", 0.0),
        active_tests=status.get("active_tests", 0),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not registered")
    return {"status": "ok"}


@app.get("/api/agents/{agent_id}/next-case", response_model=Optional[AgentWorkItem])
async def agent_next_case(agent_id: str):
    """Provide the next pending test case for an agent"""
    work = await agent_manager.request_work(agent_id)
    if not work:
        return JSONResponse(status_code=204, content=None)
    return work


@app.post("/api/agents/{agent_id}/result")
async def agent_submit_result(agent_id: str, result: AgentTestResult):
    """Agent submits a test case result"""
    response = await orchestrator.handle_agent_result(agent_id, result)
    return response


# ========== System Endpoints ==========


@app.get("/api/system/health")
async def system_health():
    """System health check"""
    return {
        "status": "healthy",
        "active_sessions": len(orchestrator.active_tasks),
        "total_sessions": len(orchestrator.sessions),
        "corpus_seeds": len(corpus_store.get_seed_ids()),
    }


@app.get("/api/system/config")
async def get_config():
    """Get system configuration (sanitized)"""
    return {
        "plugins_dir": str(settings.plugins_dir),
        "max_concurrent_tests": settings.max_concurrent_tests,
        "mutation_timeout_sec": settings.mutation_timeout_sec,
    }


if __name__ == "__main__":
    import uvicorn

    logger.info(
        "starting_fuzzer_core",
        host=settings.api_host,
        port=settings.api_port,
    )

    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
