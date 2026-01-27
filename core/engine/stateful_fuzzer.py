"""
Stateful fuzzing engine - follows protocol state machines

This module enables state-aware fuzzing for protocols that define
state models with transitions. Instead of sending random messages,
it follows valid state sequences to reach deep protocol logic.
"""
import random
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import structlog

from core.config import settings
from core.engine.protocol_parser import ProtocolParser
from core.engine.protocol_utils import build_message_type_mapping

logger = structlog.get_logger()


class StatefulFuzzingSession:
    """
    Manages a stateful fuzzing session that follows protocol state machine.

    Key Concepts:
    - Maintains current protocol state
    - Selects messages valid for current state
    - Tracks state transitions based on responses
    - Fuzzes within valid state sequences

    Args:
        state_model: Protocol state machine definition from plugin
        data_model: Protocol data model from plugin
        response_model: Optional response model for parsing server responses
        progression_weight: Probability of following happy path (0.0-1.0)
    """

    def __init__(
        self,
        state_model: dict,
        data_model: dict,
        response_model: Optional[dict] = None,
        progression_weight: float = None
    ):
        self.state_model = state_model
        self.data_model = data_model
        self.response_model = response_model
        self.progression_weight = (
            progression_weight if progression_weight is not None
            else settings.stateful_progression_weight
        )

        # Current state
        self.current_state = state_model.get("initial_state", "INIT")

        # State history for coverage tracking
        self.state_history: List[Dict[str, Any]] = []

        # Parser for message analysis
        self.parser = ProtocolParser(data_model)

        # Response parser if response_model is provided
        self.response_parser = ProtocolParser(response_model) if response_model else None

        # Coverage offsets for resumed sessions without full history
        self.coverage_offset: Dict[str, int] = {}
        self.transition_offset: Dict[str, int] = {}
        self.resumed_from_offsets = False
        self.has_new_activity = False

        # Build message type to command/message mapping
        self.message_type_field: Optional[str] = None
        self._build_message_type_mapping()

        logger.info(
            "stateful_session_created",
            initial_state=self.current_state,
            num_states=len(state_model.get("states", [])),
            num_transitions=len(state_model.get("transitions", []))
        )

    def restore_state(
        self,
        current_state: Optional[str],
        state_history: Optional[List[Dict[str, Any]]],
        state_coverage: Optional[Dict[str, int]] = None,
        transition_coverage: Optional[Dict[str, int]] = None
    ) -> None:
        """
        Restore stateful session state from persisted data.

        Used when resuming a session after restart to continue from where it left off
        instead of resetting to initial state.

        Args:
            current_state: The state to restore (if None, keeps initial state)
            state_history: The state transition history to restore (if None, keeps empty)
            state_coverage: State visit counts to restore (optional, will be recalculated if None)
            transition_coverage: Transition counts to restore (optional, will be recalculated if None)

        Note: state_history is not persisted to disk, so coverage dicts must be provided
        to avoid losing coverage data on resume. If state_history is provided, coverage
        can be recalculated from it.
        """
        if current_state:
            self.current_state = current_state
            logger.info(
                "stateful_session_state_restored",
                restored_state=current_state,
                original_initial_state=self.state_model.get("initial_state", "INIT")
            )

        if state_history:
            self.state_history = state_history
            self.resumed_from_offsets = False
            logger.info(
                "stateful_session_history_restored",
                history_entries=len(state_history)
            )
        else:
            if state_coverage:
                self.coverage_offset = dict(state_coverage)
            if transition_coverage:
                self.transition_offset = dict(transition_coverage)
            if state_coverage or transition_coverage:
                self.resumed_from_offsets = True
                logger.info(
                    "stateful_session_coverage_restored",
                    state_coverage_entries=len(state_coverage or {}),
                    transition_coverage_entries=len(transition_coverage or {}),
                )

    def _build_message_type_mapping(self) -> None:
        """
        Build mapping from message types to command values using shared utility.

        For kevin protocol:
        - CONNECT -> 0x01
        - DATA -> 0x02
        - DISCONNECT -> 0x03
        """
        # Use shared protocol analysis utility
        self.message_type_field, self.message_type_to_command = build_message_type_mapping(
            self.data_model
        )

        if self.message_type_field:
            logger.debug(
                "message_type_mapping_built",
                field=self.message_type_field,
                mapping=self.message_type_to_command,
            )

    def get_valid_transitions(self) -> List[dict]:
        """
        Returns list of valid transitions from current state.

        Example: In CONNECTED state, returns [AUTH, DISCONNECT]

        Returns:
            List of transition dicts that can be taken from current state
        """
        transitions = [
            t for t in self.state_model.get("transitions", [])
            if t.get("from") == self.current_state
        ]

        logger.debug(
            "valid_transitions",
            state=self.current_state,
            count=len(transitions),
            types=[t.get("message_type") for t in transitions]
        )

        return transitions

    def get_termination_states(self) -> List[str]:
        """
        Identify terminal/termination states in the protocol.

        Terminal states are:
        1. States with no outgoing transitions (dead ends)
        2. States whose names suggest termination (DISCONNECTED, CLOSED, etc.)

        Returns:
            List of state names considered termination states
        """
        termination_keywords = [
            "disconnect", "terminated", "closed", "end", "exit",
            "final", "done", "complete", "shutdown", "bye"
        ]

        termination_states = set()

        # Get all states with outgoing transitions
        states_with_outgoing = set(
            t.get("from") for t in self.state_model.get("transitions", [])
        )

        # States with no outgoing transitions are terminal
        for state in self.state_model.get("states", []):
            if state not in states_with_outgoing:
                termination_states.add(state)

            # States with termination-related names
            state_lower = state.lower()
            if any(keyword in state_lower for keyword in termination_keywords):
                termination_states.add(state)

        logger.debug(
            "termination_states_identified",
            states=list(termination_states),
            count=len(termination_states)
        )

        return list(termination_states)

    def get_transitions_to_termination(self) -> List[dict]:
        """
        Get transitions that lead to termination states.

        Useful for testing cleanup/teardown code paths.

        Returns:
            List of transition dicts that lead to termination states
        """
        termination_states = set(self.get_termination_states())

        termination_transitions = [
            t for t in self.state_model.get("transitions", [])
            if t.get("to") in termination_states
        ]

        logger.debug(
            "termination_transitions_found",
            count=len(termination_transitions),
            message_types=[t.get("message_type") for t in termination_transitions]
        )

        return termination_transitions

    def select_transition(self) -> Optional[dict]:
        """
        Choose which valid transition to take.

        Strategy:
        - progression_weight (default 80%): Follow intended state progression
        - 1-progression_weight (default 20%): Try other valid transitions

        Returns:
            Selected transition dict, or None if no valid transitions
        """
        valid_transitions = self.get_valid_transitions()

        if not valid_transitions:
            logger.warning(
                "no_valid_transitions",
                state=self.current_state,
                resetting=True
            )
            return None

        # If only one transition, use it
        if len(valid_transitions) == 1:
            return valid_transitions[0]

        # Multiple transitions - use weighted selection
        if random.random() < self.progression_weight:
            # Follow "happy path" - usually the first transition
            # (assumes plugin author listed transitions in logical order)
            selected = valid_transitions[0]
            logger.debug("selected_progression_path", transition=selected)
        else:
            # Take unexpected but valid transition
            selected = random.choice(valid_transitions)
            logger.debug("selected_alternative_path", transition=selected)

        return selected

    def get_message_type_for_state(self) -> Optional[str]:
        """
        Get the message type to send for current state.

        Returns:
            Message type string (e.g., "CONNECT"), or None if terminal state
        """
        transition = self.select_transition()
        if not transition:
            return None

        return transition.get("message_type")

    def find_seed_for_message_type(
        self,
        message_type: str,
        seeds: List[bytes]
    ) -> Optional[bytes]:
        """
        Find a seed message that matches the desired message type.

        Args:
            message_type: Desired message type (e.g., "CONNECT")
            seeds: Available seed messages

        Returns:
            Matching seed, or None if not found
        """
        # Get command value for this message type
        command_value = self.message_type_to_command.get(message_type)

        if command_value is None or not self.message_type_field:
            logger.warning(
                "unknown_message_type",
                message_type=message_type,
                available=list(self.message_type_to_command.keys())
            )
            return None

        # Search seeds for matching command
        for seed in seeds:
            try:
                fields = self.parser.parse(seed)
                if fields.get(self.message_type_field) == command_value:
                    logger.debug(
                        "found_seed_for_type",
                        message_type=message_type,
                        command=hex(command_value),
                        seed_size=len(seed)
                    )
                    return seed
            except Exception as e:
                logger.debug("seed_parse_failed", error=str(e))
                continue

        logger.warning(
            "no_seed_found_for_type",
            message_type=message_type,
            command=hex(command_value) if command_value else None
        )
        return None

    def identify_message_type(self, message: bytes) -> Optional[str]:
        """
        Identify the message type from a message's command field.

        Args:
            message: Binary message

        Returns:
            Message type string, or None if can't identify
        """
        try:
            fields = self.parser.parse(message)
            if not self.message_type_field:
                return None

            command_value = fields.get(self.message_type_field)

            if command_value is None:
                return None

            # Reverse lookup: 0x01 -> "CONNECT"
            for msg_type, cmd_val in self.message_type_to_command.items():
                if cmd_val == command_value:
                    return msg_type

            logger.debug(
                "unknown_command_value",
                command=hex(command_value) if isinstance(command_value, int) else command_value
            )
            return None

        except Exception as e:
            logger.debug("message_type_identification_failed", error=str(e))
            return None

    def update_state(
        self,
        sent_message: bytes,
        response: Optional[bytes],
        execution_result: str
    ) -> None:
        """
        Update state based on sent message and response.

        Args:
            sent_message: Message that was sent
            response: Target's response (None if no response)
            execution_result: Test result ("pass", "crash", "hang", etc.)
        """
        # Identify what message type was sent
        message_type = self.identify_message_type(sent_message)

        if not message_type:
            logger.debug("cannot_identify_message_type")
            return

        # Find matching transition
        transition = self._find_transition(self.current_state, message_type)

        if not transition:
            logger.debug(
                "unexpected_message_for_state",
                state=self.current_state,
                message_type=message_type
            )
            return

        # Record transition attempt
        transition_record = {
            "from": self.current_state,
            "message_type": message_type,
            "execution_result": execution_result,
            "timestamp": datetime.utcnow().isoformat()
        }

        # Check if transition should succeed
        if execution_result == "pass":
            # Check expected response if specified
            expected_response = transition.get("expected_response")

            if expected_response and response:
                # Validate the response matches expected message type
                response_matches = self._validate_expected_response(
                    response, expected_response
                )
                if not response_matches:
                    logger.warning(
                        "unexpected_response_type",
                        state=self.current_state,
                        message_type=message_type,
                        expected=expected_response,
                        actual=self._identify_response_message_type(response)
                    )
            else:
                # No expected response specified, assume success
                response_matches = True

            if response_matches:
                # Successful transition
                old_state = self.current_state
                self.current_state = transition.get("to", self.current_state)

                transition_record["to"] = self.current_state
                transition_record["success"] = True

                logger.info(
                    "state_transition",
                    from_state=old_state,
                    to_state=self.current_state,
                    message_type=message_type
                )
            else:
                transition_record["success"] = False
                transition_record["reason"] = "unexpected_response"
        else:
            # Crash or hang - no state change
            transition_record["success"] = False
            transition_record["reason"] = execution_result

        self.state_history.append(transition_record)
        self.has_new_activity = True

    def _find_transition(
        self,
        from_state: str,
        message_type: str
    ) -> Optional[dict]:
        """
        Find transition matching state and message type.

        Args:
            from_state: Current state
            message_type: Message type being sent

        Returns:
            Matching transition dict, or None
        """
        for transition in self.state_model.get("transitions", []):
            if (transition.get("from") == from_state and
                transition.get("message_type") == message_type):
                return transition

        return None

    def reset_to_initial_state(self) -> None:
        """
        Reset state machine to initial state.

        Useful for:
        - Terminal states (no valid transitions)
        - Exploring different paths
        - Simulating reconnection
        """
        old_state = self.current_state
        self.current_state = self.state_model.get("initial_state", "INIT")

        logger.info(
            "state_reset",
            from_state=old_state,
            to_state=self.current_state
        )

    def get_state_coverage(self) -> Dict[str, int]:
        """
        Calculate state coverage - which states have been visited and how often.

        Returns:
            Dict mapping state name to visit count
        """
        # Count visits to each state
        visits = Counter(
            record.get("to")
            for record in self.state_history
            if record.get("success") and record.get("to")
        )

        # Include current state unless we're resuming from offsets with no new activity yet
        if self.current_state and not (self.resumed_from_offsets and not self.has_new_activity):
            visits[self.current_state] = visits.get(self.current_state, 0) + 1

        # Apply coverage offsets from resumed sessions
        for state, count in self.coverage_offset.items():
            visits[state] = visits.get(state, 0) + count

        # Add zeros for unvisited states
        for state in self.state_model.get("states", []):
            if state not in visits:
                visits[state] = 0

        return dict(visits)

    def get_transition_coverage(self) -> Dict[str, int]:
        """
        Calculate transition coverage - which transitions have been taken.

        Returns:
            Dict mapping "FROM->TO" to count
        """
        successful_transitions = [
            record for record in self.state_history
            if record.get("success")
        ]

        transition_keys = [
            f"{record['from']}->{record.get('to', '?')}"
            for record in successful_transitions
        ]

        counts = Counter(transition_keys)

        # Apply transition offsets from resumed sessions
        for transition, count in self.transition_offset.items():
            counts[transition] = counts.get(transition, 0) + count

        return dict(counts)

    def get_coverage_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive coverage statistics.

        Returns:
            Dict with state coverage, transition coverage, and metrics
        """
        state_coverage = self.get_state_coverage()
        transition_coverage = self.get_transition_coverage()

        total_states = len(self.state_model.get("states", []))
        visited_states = sum(1 for count in state_coverage.values() if count > 0)

        total_transitions = len(self.state_model.get("transitions", []))
        taken_transitions = len([c for c in transition_coverage.values() if c > 0])

        return {
            "current_state": self.current_state,
            "state_coverage": state_coverage,
            "transition_coverage": transition_coverage,
            "states_visited": visited_states,
            "states_total": total_states,
            "state_coverage_pct": (visited_states / total_states * 100) if total_states > 0 else 0,
            "transitions_taken": taken_transitions,
            "transitions_total": total_transitions,
            "transition_coverage_pct": (taken_transitions / total_transitions * 100) if total_transitions > 0 else 0,
            "total_transitions_executed": len(self.state_history)
        }

    def should_reset(self, iteration: int, reset_interval: int = 100) -> bool:
        """
        Determine if state should be reset.

        Args:
            iteration: Current fuzzing iteration
            reset_interval: Reset every N iterations

        Returns:
            True if should reset
        """
        # Reset periodically
        if iteration > 0 and iteration % reset_interval == 0:
            return True

        # Reset if stuck in terminal state with no valid transitions
        if not self.get_valid_transitions():
            return True

        return False

    def _identify_response_message_type(self, response: bytes) -> Optional[str]:
        """
        Identify the message type from a response.

        Args:
            response: Binary response message

        Returns:
            Message type string, or None if can't identify
        """
        if not self.response_parser:
            # No response model - can't identify response type
            return None

        try:
            fields = self.response_parser.parse(response)

            # Look for message type field in response
            # Try common field names first
            for field_name in ["message_type", "command", "type", "msg_type"]:
                if field_name in fields:
                    value = fields[field_name]

                    # Reverse lookup: numeric value -> symbolic name
                    for msg_type, cmd_val in self.message_type_to_command.items():
                        if cmd_val == value:
                            return msg_type

            return None

        except Exception as e:
            logger.debug("response_type_identification_failed", error=str(e))
            return None

    def _validate_expected_response(
        self,
        response: bytes,
        expected_response: str
    ) -> bool:
        """
        Validate that the response matches the expected message type.

        Args:
            response: Binary response message
            expected_response: Expected message type (e.g., "HANDSHAKE_RESPONSE")

        Returns:
            True if response matches expected type, False otherwise
        """
        if not response:
            return False

        # Identify actual response type
        actual_response_type = self._identify_response_message_type(response)

        if actual_response_type is None:
            # Can't identify response type - be lenient and assume it's ok
            logger.debug(
                "cannot_validate_response",
                expected=expected_response,
                reason="no_response_parser_or_type_field"
            )
            return True

        # Compare actual vs expected
        matches = actual_response_type == expected_response

        if matches:
            logger.debug(
                "response_validated",
                expected=expected_response,
                actual=actual_response_type
            )
        else:
            logger.info(
                "response_mismatch",
                expected=expected_response,
                actual=actual_response_type
            )

        return matches
