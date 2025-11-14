"""Route bundles for the Core API."""
from . import agents, corpus, plugins, protocol_tools, sessions, system, tests, walker

ROUTERS = [
    plugins.router,
    sessions.router,
    tests.router,
    corpus.router,
    agents.router,
    system.router,
    protocol_tools.router,
    walker.router,
]
