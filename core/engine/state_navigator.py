"""
State Navigator - Handles state machine navigation for stateful fuzzing.

This module provides high-level state machine navigation strategies for
stateful protocol fuzzing, wrapping the lower-level StatefulFuzzingSession.

Component Overview:
-------------------
The StateNavigator provides intelligent seed selection based on:
- Current protocol state machine position
- Desired fuzzing mode (breadth-first, depth-first, targeted)
- Coverage goals (visit all states, explore transitions)
- Termination fuzzing (exercise cleanup/teardown code)

Key Responsibilities:
--------------------
1. Fuzzing Mode Strategies:
   - breadth_first: Prioritize least-visited states for coverage
   - depth_first: Follow first valid transition for deep paths
   - targeted: Navigate toward specific target state
   - random: Default fallback selection

2. Termination Fuzzing:
   - Inject termination tests before state resets
   - Find paths to termination states
   - Track termination test counts
   - Handle pending termination reset state

3. Reset Interval Management:
   - Determine when to reset to initial state
   - Mode-specific reset intervals (BFS shorter, DFS longer)
   - Session-specific override via configuration

4. State Updates:
   - Update state after test execution
   - Sync coverage to session model
   - Track tests since last reset
   - Handle periodic resets

Integration Points:
------------------
- Wraps StatefulFuzzingSession for state tracking
- Used by FuzzingLoopCoordinator for seed selection
- Updates FuzzSession with coverage metrics
- Uses settings for termination/reset intervals

Usage Example:
-------------
    # Create navigator wrapping a stateful session
    navigator = StateNavigator(stateful_session, session)

    # Select seed based on fuzzing mode
    seed = navigator.select_message_for_mode(session, seeds, iteration)

    # Check if termination test should be injected
    if navigator.should_inject_termination_test(session, iteration):
        seed = navigator.select_termination_message(session, seeds)

    # Update state after test execution
    navigator.update_state(session, test_data, response, result, iteration)

State Coverage Tracking:
-----------------------
The navigator automatically syncs coverage metrics to the session:
- state_coverage: Dict of state -> visit count
- transition_coverage: Dict of "from->to" -> count
- coverage_snapshot: Final coverage stats when session ends

Note:
----
This module is part of the Phase 5 orchestrator decomposition. It extracts
state navigation into a focused, testable component.

See Also:
--------
- core/engine/stateful_fuzzer.py - Underlying state machine implementation
- core/engine/fuzzing_loop.py - Uses StateNavigator for seed selection
- docs/developer/03_stateful_fuzzing.md - Stateful fuzzing documentation
"""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import structlog

from core.config import settings
from core.models import FuzzSession, TestCaseResult

if TYPE_CHECKING:
    from core.engine.stateful_fuzzer import StatefulFuzzingSession

logger = structlog.get_logger()


class StateNavigator:
    """
    Manages state machine navigation for stateful fuzzing sessions.

    Handles:
    - Seed selection based on fuzzing mode (breadth-first, depth-first, targeted)
    - Termination test injection for cleanup/teardown coverage
    - State reset interval management
    - Path finding for targeted state navigation

    This component wraps a StatefulFuzzingSession and provides higher-level
    navigation strategies.
    """

    def __init__(
        self,
        stateful_session: "StatefulFuzzingSession",
        session: Optional[FuzzSession] = None,
    ):
        """
        Initialize the StateNavigator.

        Args:
            stateful_session: The underlying StatefulFuzzingSession
            session: Optional FuzzSession for configuration (can be set later)
        """
        self.stateful_session = stateful_session
        self._session = session

    @property
    def current_state(self) -> str:
        """Get the current state machine state."""
        return self.stateful_session.current_state

    def get_reset_interval(self, session: Optional[FuzzSession] = None) -> int:
        """
        Determine state reset interval based on session config and fuzzing mode.

        Args:
            session: Fuzzing session (uses stored session if None)

        Returns:
            Reset interval in iterations
        """
        session = session or self._session
        if session is None:
            return settings.stateful_reset_interval_random

        # Use session-specific interval if configured
        if session.session_reset_interval is not None:
            return session.session_reset_interval

        # Fall back to mode-based defaults
        if session.fuzzing_mode == "breadth_first":
            return settings.stateful_reset_interval_bfs
        elif session.fuzzing_mode == "depth_first":
            return settings.stateful_reset_interval_dfs
        elif session.fuzzing_mode == "targeted" and session.target_state:
            return settings.stateful_reset_interval_targeted
        else:
            return settings.stateful_reset_interval_random

    def should_inject_termination_test(
        self,
        session: FuzzSession,
        iteration: int,
    ) -> bool:
        """
        Determine if we should inject a termination test.

        Termination tests exercise cleanup/teardown code by forcing
        transitions to termination states.

        Args:
            session: Fuzzing session
            iteration: Current iteration

        Returns:
            True if should inject termination test
        """
        if not session.enable_termination_fuzzing:
            return False

        if session.termination_reset_pending:
            return True

        # Check if there are termination transitions available
        termination_transitions = self.stateful_session.get_transitions_to_termination()
        if not termination_transitions:
            return False

        # Get reset interval for this session
        reset_interval = self.get_reset_interval(session)

        # Inject termination test when we're about to reset
        tests_until_reset = (
            reset_interval - (iteration % reset_interval)
            if reset_interval > 0
            else 999
        )
        if tests_until_reset <= settings.termination_test_window:
            session.termination_reset_pending = True
            return True

        # Also inject periodically
        termination_interval = min(
            settings.termination_test_interval,
            max(reset_interval // 2, 10) if reset_interval else settings.termination_test_interval,
        )
        if iteration > 0 and iteration % termination_interval == 0:
            session.termination_reset_pending = True
            return True

        return False

    def select_termination_message(
        self,
        session: FuzzSession,
        seeds: List[bytes],
    ) -> Optional[bytes]:
        """
        Select a message that will trigger a termination transition.

        Args:
            session: Fuzzing session
            seeds: Available seed messages

        Returns:
            Seed message for termination, or None if not available
        """
        termination_transitions = self.stateful_session.get_transitions_to_termination()
        if not termination_transitions:
            return None

        current_state = self.current_state

        # Find a transition from current state that leads to termination
        for transition in termination_transitions:
            if transition.get("from") == current_state:
                message_type = transition.get("message_type")
                if message_type:
                    seed = self.stateful_session.find_seed_for_message_type(
                        message_type, seeds
                    )
                    if seed:
                        logger.info(
                            "termination_test_selected",
                            current_state=current_state,
                            message_type=message_type,
                            target_state=transition.get("to"),
                        )
                        session.termination_tests += 1
                        return seed

        # No direct termination from current state - try navigating
        for transition in termination_transitions:
            from_state = transition.get("from")
            if from_state and from_state != current_state:
                nav_message = self.find_path_to_state(from_state)
                if nav_message:
                    seed = self.stateful_session.find_seed_for_message_type(
                        nav_message, seeds
                    )
                    if seed:
                        logger.debug(
                            "navigating_toward_termination",
                            current_state=current_state,
                            intermediate_target=from_state,
                        )
                        return seed

        return None

    def select_message_for_mode(
        self,
        session: FuzzSession,
        seeds: List[bytes],
        iteration: int,
    ) -> Optional[bytes]:
        """
        Select appropriate message based on fuzzing mode and targeting.

        Args:
            session: Fuzzing session
            seeds: Available seed messages
            iteration: Current iteration

        Returns:
            Selected seed message, or None for fallback
        """
        if session.fuzzing_mode == "breadth_first":
            return self._select_breadth_first(seeds)

        elif session.fuzzing_mode == "depth_first":
            return self._select_depth_first(seeds)

        elif session.fuzzing_mode == "targeted":
            return self._select_targeted(session, seeds, iteration)

        return None

    def _select_breadth_first(self, seeds: List[bytes]) -> Optional[bytes]:
        """Select message leading to least-visited state."""
        valid_transitions = self.stateful_session.get_valid_transitions()
        if not valid_transitions:
            return None

        state_coverage = self.stateful_session.get_state_coverage()

        # Find transition leading to least-visited state
        best_transition = min(
            valid_transitions,
            key=lambda t: state_coverage.get(t.get("to", ""), 0),
        )

        message_type = best_transition.get("message_type")
        if message_type:
            return self.stateful_session.find_seed_for_message_type(message_type, seeds)

        return None

    def _select_depth_first(self, seeds: List[bytes]) -> Optional[bytes]:
        """Select first valid message (deep paths)."""
        message_type = self.stateful_session.get_message_type_for_state()
        if message_type:
            return self.stateful_session.find_seed_for_message_type(message_type, seeds)
        return None

    def _select_targeted(
        self,
        session: FuzzSession,
        seeds: List[bytes],
        iteration: int,
    ) -> Optional[bytes]:
        """Select message to reach or stay in target state."""
        if self._should_navigate_to_target(session):
            # Navigate: select message that moves toward target
            message_type = self.find_path_to_state(session.target_state)
            if message_type:
                return self.stateful_session.find_seed_for_message_type(
                    message_type, seeds
                )
        else:
            # Already at target - select any valid message
            message_type = self.stateful_session.get_message_type_for_state()
            if message_type:
                return self.stateful_session.find_seed_for_message_type(
                    message_type, seeds
                )

        return None

    def _should_navigate_to_target(self, session: FuzzSession) -> bool:
        """Determine if we should navigate to target state."""
        if session.fuzzing_mode != "targeted" or not session.target_state:
            return False
        return self.current_state != session.target_state

    def find_path_to_state(self, target_state: str) -> Optional[str]:
        """
        Find message type that moves toward target state.

        Uses BFS to find shortest path to target state.

        Args:
            target_state: Desired target state

        Returns:
            Message type to send, or None if unreachable
        """
        current = self.current_state
        if current == target_state:
            return self.stateful_session.get_message_type_for_state()

        # BFS to find path
        queue = deque([(current, [])])
        visited = {current}

        state_model = self.stateful_session.state_model
        transitions = state_model.get("transitions", [])

        while queue:
            state, path = queue.popleft()

            for transition in transitions:
                if transition.get("from") != state:
                    continue

                to_state = transition.get("to")
                if to_state in visited:
                    continue

                new_path = path + [transition]

                if to_state == target_state:
                    # Found path - return first step's message type
                    if new_path:
                        return new_path[0].get("message_type")
                    return None

                visited.add(to_state)
                queue.append((to_state, new_path))

        return None

    def update_state(
        self,
        session: FuzzSession,
        test_data: bytes,
        response: Optional[bytes],
        result: TestCaseResult,
        iteration: int,
    ) -> None:
        """
        Update stateful fuzzing state after test execution.

        Tracks reset statistics and handles termination fuzzing.

        Args:
            session: Fuzzing session
            test_data: The test data that was sent
            response: Response from target (if any)
            result: Test result
            iteration: Current iteration
        """
        # Update state based on response
        self.stateful_session.update_state(
            test_data,
            response,
            result.value if result else "unknown",
        )

        # Sync coverage to session
        session.current_state = self.current_state
        session.state_coverage = self.stateful_session.get_state_coverage()
        session.transition_coverage = self.stateful_session.get_transition_coverage()

        # Track tests since last reset
        session.tests_since_last_reset += 1

        # Handle termination reset if pending
        if session.termination_reset_pending:
            termination_states = set(self.stateful_session.get_termination_states())
            if self.current_state in termination_states:
                logger.info(
                    "termination_state_reached",
                    session_id=session.id,
                    state=self.current_state,
                    iteration=iteration,
                )
                session.termination_reset_pending = False
                self.stateful_session.reset_to_initial_state()
                session.session_resets += 1
                session.tests_since_last_reset = 0
                return

        # Check for periodic reset
        reset_interval = self.get_reset_interval(session)
        if self.stateful_session.should_reset(iteration, reset_interval=reset_interval):
            if session.termination_reset_pending:
                logger.debug(
                    "reset_deferred_for_termination",
                    session_id=session.id,
                    iteration=iteration,
                    current_state=self.current_state,
                    reset_interval=reset_interval,
                )
                return

            logger.debug("periodic_state_reset", iteration=iteration)
            self.stateful_session.reset_to_initial_state()
            session.session_resets += 1
            session.tests_since_last_reset = 0

    def get_coverage_stats(self) -> Dict[str, Any]:
        """Get coverage statistics from the underlying stateful session."""
        return self.stateful_session.get_coverage_stats()

    def reset(self) -> None:
        """Reset to initial state."""
        self.stateful_session.reset_to_initial_state()
