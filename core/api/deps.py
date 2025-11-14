"""Shared FastAPI dependencies for Core API routers."""
from functools import lru_cache

from core.agents.manager import agent_manager
from core.corpus.store import CorpusStore
from core.engine.orchestrator import orchestrator
from core.plugin_loader import plugin_manager


@lru_cache(maxsize=1)
def get_corpus_store() -> CorpusStore:
    return CorpusStore()


def get_agent_manager():
    return agent_manager


def get_orchestrator():
    return orchestrator


def get_plugin_manager():
    return plugin_manager
