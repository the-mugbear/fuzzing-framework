"""
Seed Synthesizer - Auto-generates baseline seeds from data_model definitions

Instead of requiring users to manually craft binary seeds, this module analyzes
the protocol data_model and automatically generates valid baseline test cases.
"""
from typing import Any, Dict, List, Optional

import structlog

from core.engine.protocol_parser import ProtocolParser

logger = structlog.get_logger()


class SeedSynthesizer:
    """
    Automatically generate baseline seeds from protocol data_model.

    Generates seeds by:
    1. Creating a minimal valid message using default values
    2. Generating variants for enum/values fields
    3. Creating state transition messages (if state_model present)
    """

    def __init__(self, data_model: Dict[str, Any], state_model: Optional[Dict[str, Any]] = None):
        """
        Initialize synthesizer with protocol models.

        Args:
            data_model: Protocol data model with 'blocks' list
            state_model: Optional state machine model
        """
        self.data_model = data_model
        self.state_model = state_model or {}
        self.blocks = data_model.get('blocks', [])
        self.parser = ProtocolParser(data_model)

    def synthesize_seeds(self) -> List[bytes]:
        """
        Generate baseline seeds from data_model.

        Returns:
            List of synthesized seed messages
        """
        seeds = []

        # 1. Generate minimal valid message (all defaults)
        try:
            minimal_seed = self._build_minimal_message()
            seeds.append(minimal_seed)
            logger.debug("synthesized_minimal_seed", size=len(minimal_seed))
        except Exception as e:
            logger.warning("failed_to_synthesize_minimal_seed", error=str(e))

        # 2. Generate seeds for enum/values field variants
        enum_seeds = self._generate_enum_variants()
        seeds.extend(enum_seeds)
        logger.debug("synthesized_enum_variants", count=len(enum_seeds))

        # 3. Generate seeds for state transitions (if state model present)
        if self.state_model:
            transition_seeds = self._generate_transition_seeds()
            seeds.extend(transition_seeds)
            logger.debug("synthesized_transition_seeds", count=len(transition_seeds))

        # Deduplicate seeds
        unique_seeds = []
        seen = set()
        for seed in seeds:
            if seed not in seen:
                unique_seeds.append(seed)
                seen.add(seed)

        logger.info("seed_synthesis_complete", total=len(unique_seeds))
        return unique_seeds

    def _build_minimal_message(self) -> bytes:
        """
        Build a minimal valid message using default values from blocks.

        Returns:
            Serialized message bytes
        """
        fields = {}

        for block in self.blocks:
            field_name = block['name']
            field_type = block['type']

            # Use explicit default if provided
            if 'default' in block:
                fields[field_name] = block['default']
            else:
                # Generate minimal valid value based on type
                fields[field_name] = self._get_minimal_value(block)

        return self.parser.serialize(fields)

    def _generate_enum_variants(self) -> List[bytes]:
        """
        Generate seed variants for each value in enum/values fields.

        Returns:
            List of seed messages, one per enum value
        """
        seeds = []

        # Find all fields with 'values' (enums)
        enum_fields = [b for b in self.blocks if 'values' in b]

        for enum_block in enum_fields:
            field_name = enum_block['name']
            values = enum_block['values']

            # Generate one seed per enum value
            for enum_value in values.keys():
                try:
                    fields = self._build_default_fields()
                    fields[field_name] = enum_value
                    seed = self.parser.serialize(fields)
                    seeds.append(seed)

                    # If the value has a name, log it
                    value_name = values.get(enum_value, f"0x{enum_value:02x}")
                    logger.debug(
                        "synthesized_enum_seed",
                        field=field_name,
                        value=value_name,
                        size=len(seed)
                    )
                except Exception as e:
                    logger.warning(
                        "failed_to_synthesize_enum_seed",
                        field=field_name,
                        value=enum_value,
                        error=str(e)
                    )

        return seeds

    def _generate_transition_seeds(self) -> List[bytes]:
        """
        Generate seeds for state machine transitions.

        Returns:
            List of seed messages that trigger state transitions
        """
        seeds = []
        transitions = self.state_model.get('transitions', [])

        # Build a mapping of message_type to command value
        message_type_to_command = self._build_message_type_map()

        for transition in transitions:
            message_type = transition.get('message_type')
            if not message_type:
                continue

            try:
                fields = self._build_default_fields()

                # Set the command field to match the message type
                if message_type in message_type_to_command:
                    command_field, command_value = message_type_to_command[message_type]
                    fields[command_field] = command_value

                seed = self.parser.serialize(fields)
                seeds.append(seed)

                logger.debug(
                    "synthesized_transition_seed",
                    message_type=message_type,
                    transition=f"{transition.get('from')}->{transition.get('to')}",
                    size=len(seed)
                )
            except Exception as e:
                logger.warning(
                    "failed_to_synthesize_transition_seed",
                    message_type=message_type,
                    error=str(e)
                )

        return seeds

    def _build_default_fields(self) -> Dict[str, Any]:
        """
        Build a field dictionary with default values.

        Returns:
            Dictionary mapping field names to default values
        """
        fields = {}

        for block in self.blocks:
            field_name = block['name']

            if 'default' in block:
                fields[field_name] = block['default']
            else:
                fields[field_name] = self._get_minimal_value(block)

        return fields

    def _get_minimal_value(self, block: dict) -> Any:
        """
        Get minimal valid value for a field block.

        Args:
            block: Field block definition

        Returns:
            Minimal valid value for the field type
        """
        field_type = block['type']

        if field_type.startswith('uint') or field_type.startswith('int'):
            # For integer types, use 0 or first value in enum
            if 'values' in block:
                return list(block['values'].keys())[0]
            return 0

        elif field_type == 'bytes':
            # For byte fields, use empty bytes or minimal size
            size = block.get('size', 0)
            if size > 0:
                return b'\x00' * size
            return b''

        elif field_type == 'string':
            # For string fields, use empty string
            return ''

        return None

    def _build_message_type_map(self) -> Dict[str, tuple[str, int]]:
        """
        Build mapping from message_type name to (field_name, value).

        Returns:
            Dict mapping message type to (field_name, command_value) tuple
        """
        mapping = {}

        # Find the command/type field (usually has 'values' dict)
        for block in self.blocks:
            if 'values' in block:
                field_name = block['name']
                values = block['values']

                # Map value names to their numeric values
                for value, name in values.items():
                    mapping[name] = (field_name, value)

        return mapping


def synthesize_seeds_for_protocol(
    data_model: Dict[str, Any],
    state_model: Optional[Dict[str, Any]] = None
) -> List[bytes]:
    """
    Convenience function to synthesize seeds for a protocol.

    Args:
        data_model: Protocol data model
        state_model: Optional state model

    Returns:
        List of synthesized seed bytes
    """
    synthesizer = SeedSynthesizer(data_model, state_model)
    return synthesizer.synthesize_seeds()
