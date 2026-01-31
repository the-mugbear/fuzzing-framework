"""
Plugin Validator - Static analysis and validation for protocol plugins

Performs comprehensive validation of plugin definitions to catch errors
before runtime, improving the developer experience and fuzzing quality.
"""
import ast
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from core.engine.protocol_parser import ProtocolParser
from core.plugin_loader import denormalize_data_model_from_json

logger = structlog.get_logger()


class ValidationIssue:
    """Represents a validation error or warning"""

    def __init__(
        self,
        severity: str,  # "error" or "warning"
        category: str,  # e.g., "data_model", "state_model", "seeds"
        message: str,
        field: Optional[str] = None,
        suggestion: Optional[str] = None,
    ):
        self.severity = severity
        self.category = category
        self.message = message
        self.field = field
        self.suggestion = suggestion

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "field": self.field,
            "suggestion": self.suggestion,
        }


class ValidationResult:
    """Container for validation results"""

    def __init__(self):
        self.errors: List[ValidationIssue] = []
        self.warnings: List[ValidationIssue] = []

    def add_error(
        self,
        category: str,
        message: str,
        field: Optional[str] = None,
        suggestion: Optional[str] = None,
    ):
        self.errors.append(ValidationIssue("error", category, message, field, suggestion))

    def add_warning(
        self,
        category: str,
        message: str,
        field: Optional[str] = None,
        suggestion: Optional[str] = None,
    ):
        self.warnings.append(ValidationIssue("warning", category, message, field, suggestion))

    @property
    def is_valid(self) -> bool:
        """Plugin is valid if it has no errors (warnings are acceptable)"""
        return len(self.errors) == 0

    @property
    def issue_count(self) -> int:
        return len(self.errors) + len(self.warnings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


class PluginValidator:
    """
    Validates protocol plugin definitions for correctness and best practices.

    Validation levels:
    - Errors: Critical issues that will cause runtime failures
    - Warnings: Potential issues or best practice violations
    """

    VALID_FIELD_TYPES = {
        "bits",      # Arbitrary bit-width field (requires 'size' attribute)
        "bytes",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "int8",
        "int16",
        "int32",
        "int64",
        "string",
    }

    VALID_ENDIAN = {"big", "little"}
    VALID_TRANSFORM_OPS = {
        "add_constant",
        "subtract_constant",
        "xor_constant",
        "and_mask",
        "or_mask",
        "shift_left",
        "shift_right",
        "invert",
        "modulo",
    }
    VALID_GENERATORS = {"unix_timestamp", "sequence"}

    def __init__(self):
        self.result = ValidationResult()

    def validate_plugin(
        self, data_model: Dict[str, Any], state_model: Dict[str, Any]
    ) -> ValidationResult:
        """
        Perform comprehensive validation of a plugin.

        Args:
            data_model: Protocol data model dictionary
            state_model: Protocol state model dictionary

        Returns:
            ValidationResult with errors and warnings
        """
        self.result = ValidationResult()

        # Validate data model structure
        self._validate_data_model_structure(data_model)

        # Validate individual blocks
        if "blocks" in data_model:
            self._validate_blocks(data_model["blocks"])

        # Validate seeds if present
        if "seeds" in data_model and data_model["seeds"]:
            self._validate_seeds(data_model)

        # Validate state model
        self._validate_state_model(state_model, data_model)

        # Cross-validation checks
        self._validate_dependencies(data_model)

        # Validate dynamic/context fields
        self._validate_dynamic_fields(data_model)

        # Variable-length field positioning check
        self._validate_variable_length_positioning(data_model)

        logger.info(
            "plugin_validation_complete",
            valid=self.result.is_valid,
            errors=len(self.result.errors),
            warnings=len(self.result.warnings),
        )

        return self.result

    def _validate_data_model_structure(self, data_model: Dict[str, Any]):
        """Validate basic data_model structure"""
        if not isinstance(data_model, dict):
            self.result.add_error(
                "structure", "data_model must be a dictionary", suggestion="Ensure data_model is defined as a dict"
            )
            return

        # Check required fields
        if "blocks" not in data_model:
            self.result.add_error("structure", "data_model missing required 'blocks' field")
        elif not isinstance(data_model["blocks"], list):
            self.result.add_error("structure", "data_model.blocks must be a list")

        # Check optional but recommended fields
        if "name" not in data_model:
            self.result.add_warning("structure", "data_model missing 'name' field", suggestion="Add a descriptive name for your protocol")

        # Warn about empty seeds (now auto-generated, but still worth mentioning)
        if "seeds" not in data_model or not data_model.get("seeds"):
            self.result.add_warning(
                "seeds",
                "No seeds defined - will be auto-generated",
                suggestion="Consider adding manual seeds for edge cases or known scenarios",
            )

    def _validate_blocks(self, blocks: List[Dict[str, Any]]):
        """Validate individual block definitions"""
        if not blocks:
            self.result.add_error("data_model", "No blocks defined in data_model")
            return

        block_names: Set[str] = set()

        for idx, block in enumerate(blocks):
            if not isinstance(block, dict):
                self.result.add_error("data_model", f"Block {idx} is not a dictionary")
                continue

            # Required fields
            if "name" not in block:
                self.result.add_error("data_model", f"Block {idx} missing 'name' field")
                continue

            name = block["name"]

            # Check for duplicate names
            if name in block_names:
                self.result.add_error("data_model", f"Duplicate block name: '{name}'", field=name)
            block_names.add(name)

            # Validate type
            if "type" not in block:
                self.result.add_error("data_model", f"Block '{name}' missing 'type' field", field=name)
                continue

            field_type = block["type"]
            if field_type not in self.VALID_FIELD_TYPES:
                self.result.add_error(
                    "data_model",
                    f"Block '{name}' has invalid type: '{field_type}'",
                    field=name,
                    suggestion=f"Valid types: {', '.join(sorted(self.VALID_FIELD_TYPES))}",
                )

            # Type-specific validation
            self._validate_block_type_specific(block, name, field_type)

            # Validate size fields
            self._validate_block_size(block, name, field_type)

            # Validate endianness for integer types
            if field_type.startswith("uint") or field_type.startswith("int"):
                if "endian" in block and block["endian"] not in self.VALID_ENDIAN:
                    self.result.add_error(
                        "data_model",
                        f"Block '{name}' has invalid endian: '{block['endian']}'",
                        field=name,
                        suggestion="Use 'big' or 'little'",
                    )

    def _validate_dynamic_fields(self, data_model: Dict[str, Any]) -> None:
        """Validate from_context, transform, and generate attributes."""
        blocks = data_model.get("blocks", [])
        if not blocks:
            return

        for block in blocks:
            name = block.get("name", "<unnamed>")

            if "from_context" in block and not isinstance(block.get("from_context"), str):
                self.result.add_error(
                    "data_model",
                    f"Block '{name}' from_context must be a string",
                    field=name,
                    suggestion="Use from_context: 'context_key'",
                )

            if "transform" in block:
                transform = block.get("transform")
                if not isinstance(transform, list):
                    self.result.add_error(
                        "data_model",
                        f"Block '{name}' transform must be a list of operations",
                        field=name,
                    )
                else:
                    for idx, step in enumerate(transform):
                        if not isinstance(step, dict):
                            self.result.add_error(
                                "data_model",
                                f"Block '{name}' transform step {idx} must be a dict",
                                field=name,
                            )
                            continue
                        operation = step.get("operation")
                        if operation not in self.VALID_TRANSFORM_OPS:
                            self.result.add_error(
                                "data_model",
                                f"Block '{name}' transform step {idx} has invalid operation: '{operation}'",
                                field=name,
                                suggestion=f"Valid ops: {', '.join(sorted(self.VALID_TRANSFORM_OPS))}",
                            )

            if "generate" in block:
                generator = block.get("generate")
                if not isinstance(generator, str):
                    self.result.add_error(
                        "data_model",
                        f"Block '{name}' generate must be a string",
                        field=name,
                    )
                    continue

                if generator in self.VALID_GENERATORS:
                    continue

                if generator.startswith("random_bytes:"):
                    parts = generator.split(":", 1)
                    if len(parts) != 2 or not parts[1].isdigit():
                        self.result.add_error(
                            "data_model",
                            f"Block '{name}' generate random_bytes must be 'random_bytes:N'",
                            field=name,
                            suggestion="Example: generate: 'random_bytes:16'",
                        )
                else:
                    self.result.add_error(
                        "data_model",
                        f"Block '{name}' generate has unknown value: '{generator}'",
                        field=name,
                        suggestion=f"Valid: {', '.join(sorted(self.VALID_GENERATORS))} or random_bytes:N",
                    )

    def _validate_block_type_specific(self, block: Dict[str, Any], name: str, field_type: str):
        """Validate type-specific block properties"""
        # Bits fields require size attribute and validate bit_order
        if field_type == "bits":
            if "size" not in block:
                self.result.add_error(
                    "data_model",
                    f"Field '{name}' has type 'bits' but missing required 'size' attribute",
                    field=name,
                    suggestion="Add 'size' attribute (1-64 bits)",
                )
            else:
                size = block["size"]
                if not isinstance(size, int) or size < 1 or size > 64:
                    self.result.add_error(
                        "data_model",
                        f"Field '{name}' bit size must be 1-64, got {size}",
                        field=name,
                        suggestion="Use integer between 1 and 64 for bit field size",
                    )

            # Validate bit_order if present
            if "bit_order" in block:
                bit_order = block["bit_order"]
                if bit_order not in ["msb", "lsb"]:
                    self.result.add_error(
                        "data_model",
                        f"Field '{name}' bit_order must be 'msb' or 'lsb', got '{bit_order}'",
                        field=name,
                        suggestion="Use 'msb' (default) for MSB-first or 'lsb' for LSB-first",
                    )

            # Validate endian if present (for multi-byte bit fields)
            if "endian" in block:
                endian = block["endian"]
                if endian not in ["big", "little"]:
                    self.result.add_error(
                        "data_model",
                        f"Field '{name}' endian must be 'big' or 'little', got '{endian}'",
                        field=name,
                        suggestion="Use 'big' (default) for big-endian or 'little' for little-endian",
                    )

        # Bytes fields should have size or max_size
        if field_type == "bytes":
            if "size" not in block and "max_size" not in block:
                self.result.add_warning(
                    "data_model",
                    f"Bytes field '{name}' has no size or max_size - will consume all remaining data",
                    field=name,
                    suggestion="Add 'size' for fixed-size or 'max_size' for variable-size fields",
                )

        # Integer fields with values (enums)
        if "values" in block:
            values = block["values"]
            if not isinstance(values, dict):
                self.result.add_error("data_model", f"Block '{name}' values must be a dictionary", field=name)
            elif field_type.startswith("uint") or field_type.startswith("int"):
                # Validate enum values are integers
                for key in values.keys():
                    if not isinstance(key, int):
                        self.result.add_error(
                            "data_model", f"Block '{name}' has non-integer enum key: {key}", field=name
                        )

    def _validate_block_size(self, block: Dict[str, Any], name: str, field_type: str):
        """Validate size-related properties"""
        # Check for unreasonable sizes
        if "size" in block:
            size = block["size"]
            if not isinstance(size, int) or size < 0:
                self.result.add_error("data_model", f"Block '{name}' has invalid size: {size}", field=name)
            elif size > 65536:  # 64KB warning
                self.result.add_warning(
                    "data_model",
                    f"Block '{name}' has very large fixed size: {size} bytes",
                    field=name,
                    suggestion="Consider if this size is intentional",
                )

        if "max_size" in block:
            max_size = block["max_size"]
            if not isinstance(max_size, int) or max_size < 0:
                self.result.add_error("data_model", f"Block '{name}' has invalid max_size: {max_size}", field=name)
            elif max_size > 1048576:  # 1MB warning
                self.result.add_warning(
                    "data_model",
                    f"Block '{name}' has very large max_size: {max_size} bytes",
                    field=name,
                    suggestion="Large buffers may impact fuzzing performance",
                )

    def _validate_seeds(self, data_model: Dict[str, Any]):
        """Validate that seeds can be parsed with the data_model"""
        # Denormalize data_model to get bytes back
        try:
            denormalized_model = denormalize_data_model_from_json(data_model)
            parser = ProtocolParser(denormalized_model)
            seeds = denormalized_model.get("seeds", [])

            for idx, seed in enumerate(seeds):
                if not isinstance(seed, bytes):
                    self.result.add_error("seeds", f"Seed {idx + 1} is not bytes (got {type(seed).__name__})")
                    continue

                try:
                    parsed = parser.parse(seed)
                    logger.debug("seed_parsed_successfully", seed_idx=idx, fields=len(parsed))
                except Exception as e:
                    self.result.add_error(
                        "seeds",
                        f"Seed {idx + 1} failed to parse: {str(e)}",
                        suggestion="Ensure seed matches data_model structure",
                    )

        except Exception as e:
            self.result.add_error("seeds", f"Failed to validate seeds: {str(e)}")

    def _validate_state_model(self, state_model: Dict[str, Any], data_model: Dict[str, Any]):
        """Validate state machine definition"""
        if not isinstance(state_model, dict):
            self.result.add_error("state_model", "state_model must be a dictionary")
            return

        # Check basic structure
        if "initial_state" not in state_model:
            self.result.add_warning("state_model", "state_model missing 'initial_state'")

        if "states" not in state_model:
            self.result.add_warning("state_model", "state_model missing 'states' list")
        elif not isinstance(state_model["states"], list):
            self.result.add_error("state_model", "state_model.states must be a list")

        # Validate transitions
        if "transitions" in state_model:
            self._validate_transitions(state_model, data_model)

        # Check for unreachable states
        self._check_unreachable_states(state_model)

    def _validate_transitions(self, state_model: Dict[str, Any], data_model: Dict[str, Any]):
        """Validate state transitions"""
        transitions = state_model.get("transitions", [])
        states = set(state_model.get("states", []))

        # Build message_type mapping from data_model
        message_types = set()
        blocks = data_model.get("blocks", [])
        for block in blocks:
            if "values" in block:
                message_types.update(block["values"].values())

        for idx, transition in enumerate(transitions):
            if not isinstance(transition, dict):
                self.result.add_error("state_model", f"Transition {idx} is not a dictionary")
                continue

            # Check required fields
            from_state = transition.get("from")
            to_state = transition.get("to")

            if not from_state:
                self.result.add_error("state_model", f"Transition {idx} missing 'from' state")
            elif from_state not in states:
                self.result.add_error("state_model", f"Transition {idx} references undefined 'from' state: '{from_state}'")

            if not to_state:
                self.result.add_error("state_model", f"Transition {idx} missing 'to' state")
            elif to_state not in states:
                self.result.add_error("state_model", f"Transition {idx} references undefined 'to' state: '{to_state}'")

            # Check message_type if specified
            message_type = transition.get("message_type")
            if message_type and message_types and message_type not in message_types:
                self.result.add_warning(
                    "state_model",
                    f"Transition {idx} message_type '{message_type}' not found in data_model values",
                    suggestion="Ensure message_type matches a value in your command/type field",
                )

    def _check_unreachable_states(self, state_model: Dict[str, Any]):
        """Check for states that can never be reached"""
        states = set(state_model.get("states", []))
        initial_state = state_model.get("initial_state")
        transitions = state_model.get("transitions", [])

        if not states or not transitions:
            return

        # Build reachability graph
        reachable = {initial_state} if initial_state else set()
        changed = True

        while changed:
            changed = False
            for transition in transitions:
                from_state = transition.get("from")
                to_state = transition.get("to")
                if from_state in reachable and to_state not in reachable:
                    reachable.add(to_state)
                    changed = True

        # Find unreachable states
        unreachable = states - reachable
        if unreachable:
            self.result.add_warning(
                "state_model",
                f"Unreachable states detected: {', '.join(sorted(unreachable))}",
                suggestion="Add transitions to reach these states or remove them",
            )

    def _validate_dependencies(self, data_model: Dict[str, Any]):
        """Validate field dependencies (size_of, etc.)"""
        blocks = data_model.get("blocks", [])
        block_names = {b["name"] for b in blocks if "name" in b}

        for block in blocks:
            name = block.get("name")
            if not name:
                continue

            # Validate size_of references
            if block.get("is_size_field") and "size_of" in block:
                target = block["size_of"]

                # Handle both single field (string) and multiple fields (list)
                target_fields = [target] if isinstance(target, str) else target

                if not isinstance(target, (str, list)):
                    self.result.add_error(
                        "data_model",
                        f"Block '{name}' size_of must be a string or list of strings",
                        field=name,
                    )
                else:
                    # Validate each target field exists
                    for target_field in target_fields:
                        if not isinstance(target_field, str):
                            self.result.add_error(
                                "data_model",
                                f"Block '{name}' size_of contains non-string value: {target_field}",
                                field=name,
                            )
                        elif target_field not in block_names:
                            self.result.add_error(
                                "data_model",
                                f"Block '{name}' size_of references non-existent field: '{target_field}'",
                                field=name,
                                suggestion="Ensure the referenced field exists in your data_model",
                            )

                        # Check for circular dependencies
                        if target_field == name:
                            self.result.add_error(
                                "data_model",
                                f"Block '{name}' has circular size_of reference",
                                field=name
                            )

        # Check for all-immutable fields
        mutable_count = sum(1 for b in blocks if b.get("mutable", True))
        if mutable_count == 0 and blocks:
            self.result.add_warning(
                "data_model",
                "All fields are marked as mutable=False - fuzzer will have no mutations to apply",
                suggestion="Mark at least one field as mutable for effective fuzzing",
            )

    def _validate_variable_length_positioning(self, data_model: Dict[str, Any]):
        """
        Validate that variable-length fields are properly positioned.

        Variable-length fields (max_size without linked length field) must be the
        last field in the message, otherwise the parser cannot determine field
        boundaries - it will consume all remaining bytes for the variable field.

        This is a fundamental limitation of the parsing model, not a bug.
        """
        blocks = data_model.get("blocks", [])
        if not blocks:
            return

        # Build set of fields that have a length field linked to them
        fields_with_length_ref: Set[str] = set()
        for block in blocks:
            if block.get("is_size_field") and "size_of" in block:
                target = block["size_of"]
                if isinstance(target, str):
                    fields_with_length_ref.add(target)
                elif isinstance(target, list):
                    fields_with_length_ref.update(target)

        # Check each variable-length field
        last_idx = len(blocks) - 1
        for idx, block in enumerate(blocks):
            name = block.get("name")
            if not name:
                continue

            # Is this a variable-length field?
            # - Has max_size (variable upper bound)
            # - Does NOT have fixed size
            # - Does NOT have a length field linked to it
            has_max_size = "max_size" in block
            has_fixed_size = "size" in block
            has_length_ref = name in fields_with_length_ref

            if has_max_size and not has_fixed_size and not has_length_ref:
                # This is a variable-length field without a length reference
                if idx < last_idx:
                    # Not the last field - this will cause parsing issues
                    following_fields = [b.get("name", f"block_{i}") for i, b in enumerate(blocks[idx + 1:], idx + 1)]
                    self.result.add_warning(
                        "data_model",
                        f"Variable-length field '{name}' is not the last field. "
                        f"The parser will consume all remaining bytes for this field, "
                        f"leaving nothing for subsequent fields: {', '.join(following_fields[:3])}"
                        + (f" (+{len(following_fields) - 3} more)" if len(following_fields) > 3 else ""),
                        field=name,
                        suggestion=(
                            "Either: (1) Add a length field with is_size_field=True and size_of='" + name + "', "
                            "or (2) Move this field to the end of the message, "
                            "or (3) Use fixed 'size' instead of 'max_size'"
                        ),
                    )


    def validate_protocol_stack(self, protocol_stack: List[Dict[str, Any]]) -> None:
        """
        Validate protocol_stack for orchestrated sessions.

        Checks:
        - At least one fuzz_target stage
        - Valid stage roles
        - Stage data_models are valid
        - Exports reference valid response_model fields
        - from_context references in data_models
        """
        if not protocol_stack:
            return

        if not isinstance(protocol_stack, list):
            self.result.add_error(
                "protocol_stack",
                "protocol_stack must be a list of stage definitions",
            )
            return

        VALID_ROLES = {"bootstrap", "fuzz_target", "teardown"}
        fuzz_target_count = 0
        stage_names: Set[str] = set()

        for idx, stage in enumerate(protocol_stack):
            if not isinstance(stage, dict):
                self.result.add_error(
                    "protocol_stack",
                    f"Stage {idx} must be a dictionary",
                )
                continue

            # Check required fields
            if "name" not in stage:
                self.result.add_error(
                    "protocol_stack",
                    f"Stage {idx} missing 'name' field",
                )
                continue

            stage_name = stage["name"]
            if stage_name in stage_names:
                self.result.add_error(
                    "protocol_stack",
                    f"Duplicate stage name: '{stage_name}'",
                    field=stage_name,
                )
            stage_names.add(stage_name)

            # Check role
            role = stage.get("role")
            if not role:
                self.result.add_error(
                    "protocol_stack",
                    f"Stage '{stage_name}' missing 'role' field",
                    field=stage_name,
                    suggestion=f"Valid roles: {', '.join(sorted(VALID_ROLES))}",
                )
            elif role not in VALID_ROLES:
                self.result.add_error(
                    "protocol_stack",
                    f"Stage '{stage_name}' has invalid role: '{role}'",
                    field=stage_name,
                    suggestion=f"Valid roles: {', '.join(sorted(VALID_ROLES))}",
                )

            if role == "fuzz_target":
                fuzz_target_count += 1

            # Validate data_model if present
            if "data_model" in stage:
                self._validate_data_model_structure(stage["data_model"])
                if "blocks" in stage["data_model"]:
                    self._validate_blocks(stage["data_model"]["blocks"])
                    self._validate_dynamic_fields(stage["data_model"])

            # Validate response_model if present
            if "response_model" in stage:
                if not isinstance(stage["response_model"], dict):
                    self.result.add_error(
                        "protocol_stack",
                        f"Stage '{stage_name}' response_model must be a dictionary",
                        field=stage_name,
                    )
                elif "blocks" in stage["response_model"]:
                    self._validate_blocks(stage["response_model"]["blocks"])

            # Validate exports reference valid response_model fields
            if "exports" in stage:
                exports = stage["exports"]
                if not isinstance(exports, dict):
                    self.result.add_error(
                        "protocol_stack",
                        f"Stage '{stage_name}' exports must be a dictionary",
                        field=stage_name,
                    )
                elif "response_model" in stage:
                    response_fields = {
                        b.get("name")
                        for b in stage["response_model"].get("blocks", [])
                        if b.get("name")
                    }
                    for resp_field, context_key in exports.items():
                        # Handle both simple string and dict with 'as' key
                        if isinstance(context_key, dict):
                            context_key = context_key.get("as", context_key)
                        if resp_field not in response_fields:
                            self.result.add_warning(
                                "protocol_stack",
                                f"Stage '{stage_name}' exports field '{resp_field}' "
                                f"not found in response_model",
                                field=stage_name,
                                suggestion="Ensure export field names match response_model block names",
                            )

            # Validate expect conditions
            if "expect" in stage:
                expect = stage["expect"]
                if not isinstance(expect, dict):
                    self.result.add_error(
                        "protocol_stack",
                        f"Stage '{stage_name}' expect must be a dictionary",
                        field=stage_name,
                    )

        # Must have at least one fuzz_target stage
        if fuzz_target_count == 0:
            self.result.add_error(
                "protocol_stack",
                "protocol_stack must have at least one stage with role='fuzz_target'",
                suggestion="Mark one stage as the fuzzing target with 'role': 'fuzz_target'",
            )
        elif fuzz_target_count > 1:
            self.result.add_warning(
                "protocol_stack",
                f"protocol_stack has {fuzz_target_count} fuzz_target stages; "
                f"only the first will be fuzzed",
            )


def validate_plugin(data_model: Dict[str, Any], state_model: Dict[str, Any]) -> ValidationResult:
    """
    Convenience function to validate a plugin.

    Args:
        data_model: Protocol data model
        state_model: Protocol state model

    Returns:
        ValidationResult with errors and warnings
    """
    validator = PluginValidator()
    return validator.validate_plugin(data_model, state_model)


def validate_plugin_code(plugin_code: str) -> Tuple[bool, List[Dict[str, Any]], Optional[str]]:
    """
    Validate plugin Python source code.

    Performs syntax checking and extracts data_model/state_model for validation.

    Args:
        plugin_code: Python source code of the plugin

    Returns:
        Tuple of (valid, issues, plugin_name)
        - valid: True if no errors (warnings are OK)
        - issues: List of issue dictionaries
        - plugin_name: Extracted plugin name or None
    """
    issues: List[Dict[str, Any]] = []
    plugin_name = None

    # Step 1: Syntax validation
    try:
        tree = ast.parse(plugin_code)
    except SyntaxError as e:
        issues.append({
            "severity": "error",
            "category": "syntax",
            "message": f"Syntax error: {e.msg}",
            "line": e.lineno,
            "field": None
        })
        return False, issues, None

    # Step 2: Extract data_model, state_model, and protocol_stack
    data_model = None
    state_model = None
    protocol_stack = None

    try:
        # Execute code in isolated namespace
        namespace: Dict[str, Any] = {}
        exec(plugin_code, namespace)

        # Extract required attributes
        if "data_model" in namespace:
            data_model = namespace["data_model"]
            if isinstance(data_model, dict) and "name" in data_model:
                plugin_name = data_model["name"]

        if "state_model" in namespace:
            state_model = namespace["state_model"]

        # Extract optional orchestrated session attributes
        if "protocol_stack" in namespace:
            protocol_stack = namespace["protocol_stack"]

    except Exception as e:
        issues.append({
            "severity": "error",
            "category": "syntax",
            "message": f"Failed to execute plugin code: {str(e)}",
            "line": None,
            "field": None
        })
        return False, issues, plugin_name

    # Step 3: Check required attributes
    if data_model is None:
        issues.append({
            "severity": "error",
            "category": "model",
            "message": "Plugin missing required 'data_model' attribute",
            "line": None,
            "field": None
        })

    if state_model is None:
        issues.append({
            "severity": "error",
            "category": "model",
            "message": "Plugin missing required 'state_model' attribute",
            "line": None,
            "field": None
        })

    # If critical attributes are missing, stop here
    if data_model is None or state_model is None:
        return False, issues, plugin_name

    # Step 4: Run comprehensive validation
    validator = PluginValidator()
    result = validator.validate_plugin(data_model, state_model)

    # Step 5: Validate protocol_stack if present (orchestrated sessions)
    if protocol_stack is not None:
        validator.validate_protocol_stack(protocol_stack)

    # Convert ValidationResult to list of issue dicts
    for error in result.errors:
        issues.append(error.to_dict())

    for warning in result.warnings:
        issues.append(warning.to_dict())

    return result.is_valid, issues, plugin_name
