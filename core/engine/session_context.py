"""
Session Context - Encapsulates all runtime state for a fuzzing session

Replaces the parallel dictionaries in FuzzOrchestrator with a single
cohesive object that bundles all session-related runtime data.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.engine.mutators import MutationEngine
from core.engine.stateful_fuzzer import StatefulFuzzingSession
from core.models import FuzzSession


@dataclass
class SessionContext:
    """
    Encapsulates all runtime state for an active fuzzing session.

    This replaces the orchestrator's parallel dictionaries:
    - sessions -> session
    - stateful_sessions -> stateful_session
    - behavior_processors -> behavior_processor
    - response_planners -> response_planner
    - session_data_models -> data_model
    - mutation_engines -> mutation_engine (new)
    - seeds -> seeds (new)

    Benefits:
    - Single source of truth for session state
    - Impossible to have desynchronized state
    - Easier to pass context through call chains
    - Natural cleanup when session ends
    """

    # Core session metadata
    session: FuzzSession
    session_id: str

    # Protocol and data structures
    data_model: Dict
    seeds: List[bytes]

    # Fuzzing engines
    mutation_engine: MutationEngine
    stateful_session: Optional[StatefulFuzzingSession] = None

    # Behavior processors (optional, for advanced fuzzing)
    behavior_processor: Optional[object] = None  # BehaviorProcessor type
    response_planner: Optional[object] = None    # ResponsePlanner type

    # Runtime tracking
    iteration: int = 0

    def __post_init__(self):
        """Validate required fields."""
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.seeds:
            raise ValueError("seeds list cannot be empty")

    @property
    def is_stateful(self) -> bool:
        """Check if this session uses stateful fuzzing."""
        return self.stateful_session is not None

    @property
    def protocol_name(self) -> str:
        """Get protocol name from session."""
        return self.session.protocol

    def cleanup(self):
        """
        Cleanup resources associated with this context.

        Called when session is stopped or deleted.
        """
        # Release references to allow garbage collection
        self.mutation_engine = None
        self.stateful_session = None
        self.behavior_processor = None
        self.response_planner = None
        self.seeds = []
