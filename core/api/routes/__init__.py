"""Route bundles for the Core API."""
from . import probes, corpus, docs, orchestration, plugins, protocol_tools, sessions, system, tests, walker

ROUTERS = [
    plugins.router,
    sessions.router,
    orchestration.router,  # Orchestrated sessions endpoints
    tests.router,
    corpus.router,
    probes.router,
    system.router,
    protocol_tools.router,
    walker.router,
    docs.router,
]
