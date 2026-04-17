"""Shared FastAPI dependencies for Core API routers."""
from functools import lru_cache

from core.probes.manager import probe_manager
from core.corpus.store import CorpusStore
from core.engine.orchestrator import get_orchestrator as _get_orchestrator
from core.plugin_loader import plugin_manager


@lru_cache(maxsize=1)
def get_corpus_store() -> CorpusStore:
    return CorpusStore()


def get_probe_manager():
    return probe_manager


def get_orchestrator():
    """Get the global orchestrator instance."""
    return _get_orchestrator()


def get_plugin_manager():
    return plugin_manager
