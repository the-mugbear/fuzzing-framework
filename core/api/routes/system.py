"""System-level endpoints."""
from fastapi import APIRouter, Depends

from core.api.deps import get_corpus_store, get_orchestrator
from core.config import settings

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
async def system_health(orchestrator=Depends(get_orchestrator), corpus_store=Depends(get_corpus_store)):
    return {
        "status": "healthy",
        "active_sessions": len(orchestrator.active_tasks),
        "total_sessions": len(orchestrator.sessions),
        "corpus_seeds": len(corpus_store.get_seed_ids()),
    }


@router.get("/config")
async def get_config():
    return {
        "plugins_dir": str(settings.plugins_dir),
        "max_concurrent_tests": settings.max_concurrent_tests,
        "mutation_timeout_sec": settings.mutation_timeout_sec,
    }
