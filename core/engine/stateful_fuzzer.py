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

from core.engine.protocol_parser import ProtocolParser

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
        progression_weight: float = 0.8
    ):
        self.state_model = state_model
        self.data_model = data_model
        self.response_model = response_model
        self.progression_weight = progression_weight

        # Current state
        self.current_state = state_model.get("initial_state", "INIT")

        # State history for coverage tracking
        self.state_history: List[Dict[str, Any]] = []

        # Parser for message analysis
        self.parser = ProtocolParser(data_model)

        # Response parser if response_model is provided
        self.response_parser = ProtocolParser(response_model) if response_model else None

        # Build message type to command/message mapping
        self.message_type_field: Optional[str] = None
        self._build_message_type_mapping()

        logger.info(
            "stateful_session_created",
            initial_state=self.current_state,
            num_states=len(state_model.get("states", [])),
            num_transitions=len(state_model.get("transitions", []))
        )

    def _build_message_type_mapping(self) -> None:
        """
        Build mapping from message types to command values.

        For kevin protocol:
        - CONNECT -> 0x01
        - DATA -> 0x02
        - DISCONNECT -> 0x03
        """
        self.message_type_to_command: Dict[str, int] = {}

        preferred_fields = ("command", "message_type")
        fallback_block = None

        for block in self.data_model.get("blocks", []):
            if "values" not in block:
                continue
            if block.get("name") in preferred_fields:
                self.message_type_field = block["name"]
                fallback_block = block
                break
            if fallback_block is None:
                fallback_block = block

        if fallback_block and self.message_type_field is None:
            self.message_type_field = fallback_block.get("name")

        if fallback_block and self.message_type_field:
            for cmd_value, cmd_name in fallback_block["values"].items():
                self.message_type_to_command[cmd_name] = cmd_value

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

        # Include current state
        if self.current_state:
            visits[self.current_state] = visits.get(self.current_state, 0) + 1

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

        return dict(Counter(transition_keys))

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
