"""Plugin and preview endpoints."""
import base64
import random
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.api.deps import get_plugin_manager
from core.plugin_loader import decode_seeds_from_json, denormalize_data_model_from_json
from core.engine.plugin_validator import validate_plugin
from core.engine.mutators import (
    ArithmeticMutator,
    BitFlipMutator,
    ByteFlipMutator,
    HavocMutator,
    InterestingValueMutator,
    MutationEngine,
    SpliceMutator,
)
from core.engine.protocol_parser import ProtocolParser
from core.engine.structure_mutators import StructureAwareMutator
from core.models import (
    PreviewField,
    PreviewRequest,
    PreviewResponse,
    ProtocolPlugin,
    StateMachineInfo,
    StateTransition,
    TestCasePreview,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api", tags=["plugins"])


@router.get("/mutators")
async def list_mutators():
    return {"mutators": MutationEngine.available_mutators()}


@router.get("/plugins", response_model=List[str])
async def list_plugins(plugin_manager=Depends(get_plugin_manager)):
    try:
        return plugin_manager.discover_plugins()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("failed_to_list_plugins", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/plugins/{plugin_name}", response_model=ProtocolPlugin)
async def get_plugin(plugin_name: str, plugin_manager=Depends(get_plugin_manager)):
    try:
        return plugin_manager.load_plugin(plugin_name)
    except Exception as exc:
        logger.error("failed_to_load_plugin", plugin=plugin_name, error=str(exc))
        raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_name}")


@router.get("/plugins/{plugin_name}/source")
async def get_plugin_source(plugin_name: str, plugin_manager=Depends(get_plugin_manager)):
    """Get the Python source code of a plugin"""
    try:
        plugin_file = plugin_manager.plugins_dir / f"{plugin_name}.py"
        if not plugin_file.exists():
            raise HTTPException(status_code=404, detail=f"Plugin file not found: {plugin_name}")

        with open(plugin_file, 'r') as f:
            source_code = f.read()

        return {"plugin_name": plugin_name, "source_code": source_code}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("failed_to_read_plugin_source", plugin=plugin_name, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/plugins/{plugin_name}/reload", response_model=ProtocolPlugin)
async def reload_plugin(plugin_name: str, plugin_manager=Depends(get_plugin_manager)):
    try:
        plugin = plugin_manager.reload_plugin(plugin_name)
        logger.info("plugin_reloaded", plugin=plugin_name)
        return plugin
    except Exception as exc:
        logger.error("failed_to_reload_plugin", plugin=plugin_name, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/plugins/{plugin_name}/preview", response_model=PreviewResponse)
async def preview_test_cases(
    plugin_name: str,
    request: PreviewRequest,
    plugin_manager=Depends(get_plugin_manager),
):
    try:
        plugin = plugin_manager.load_plugin(plugin_name)
        # Denormalize data_model to get bytes back (for ProtocolParser)
        data_model = denormalize_data_model_from_json(plugin.data_model)
        blocks = data_model.get("blocks", [])
        seeds = data_model.get("seeds", [])  # Already decoded by denormalize
        parser = ProtocolParser(data_model)
        previews: List[TestCasePreview] = []
        state_model = plugin.state_model if plugin.state_model else {}

        if request.mode == "seeds":
            for i, seed in enumerate(seeds[: request.count]):
                previews.append(
                    _build_preview(
                        i,
                        seed,
                        parser,
                        blocks,
                        mode="baseline",
                        state_model=state_model,
                    )
                )
        elif request.mode == "mutations":
            if not seeds:
                raise HTTPException(status_code=400, detail="Protocol has no seeds defined")

            structure_mutator = StructureAwareMutator(data_model)
            byte_mutators = {
                "bitflip": BitFlipMutator(),
                "byteflip": ByteFlipMutator(),
                "arithmetic": ArithmeticMutator(),
                "interesting": InterestingValueMutator(),
                "havoc": HavocMutator(),
            }
            if len(seeds) > 1:
                byte_mutators["splice"] = SpliceMutator(seeds)

            for i in range(request.count):
                seed = random.choice(seeds)
                if i % 2 == 0:
                    mutated = structure_mutator.mutate(seed)
                    mutated_field = _detect_mutated_field(seed, mutated, parser, blocks)
                    previews.append(
                        _build_preview(
                            i,
                            mutated,
                            parser,
                            blocks,
                            mode="mutated",
                            mutation_type="structure_aware",
                            mutators_used=["structure_aware"],
                            description="Structure-aware mutation respecting protocol grammar"
                            + (f" (field: {mutated_field})" if mutated_field else ""),
                            state_model=state_model,
                        )
                    )
                else:
                    mutator_name = random.choice(list(byte_mutators.keys()))
                    mutator = byte_mutators[mutator_name]
                    mutated = mutator.mutate(seed)
                    previews.append(
                        _build_preview(
                            i,
                            mutated,
                            parser,
                            blocks,
                            mode="mutated",
                            mutation_type="byte_level",
                            mutators_used=[mutator_name],
                            description=_get_mutator_description(mutator_name),
                            state_model=state_model,
                        )
                    )
        elif request.mode == "field_focus":
            if not request.focus_field:
                raise HTTPException(status_code=400, detail="focus_field required for field_focus mode")
            if not seeds:
                raise HTTPException(status_code=400, detail="Protocol has no seeds defined")
            structure_mutator = StructureAwareMutator(data_model)
            for i in range(request.count):
                seed = random.choice(seeds)
                mutated = structure_mutator.mutate(seed)
                previews.append(
                    _build_preview(
                        i,
                        mutated,
                        parser,
                        blocks,
                        mode="mutated",
                        focus_field=request.focus_field,
                        state_model=state_model,
                    )
                )
        else:
            raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")

        return PreviewResponse(
            protocol=plugin_name,
            previews=previews,
            state_machine=_build_state_machine_info(plugin),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("preview_generation_failed", plugin=plugin_name, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


def _build_preview(
    preview_id: int,
    data: bytes,
    parser: ProtocolParser,
    blocks: List[dict],
    mode: str = "baseline",
    mutation_type: Optional[str] = None,
    mutators_used: Optional[List[str]] = None,
    description: Optional[str] = None,
    focus_field: Optional[str] = None,
    state_model: Optional[dict] = None,
) -> TestCasePreview:
    try:
        fields_dict = parser.parse(data)
    except Exception as exc:
        logger.warning("preview_parse_failed", error=str(exc))
        fields_dict = {}

    preview_fields: List[PreviewField] = []
    for block in blocks:
        field_name = block["name"]
        field_value = fields_dict.get(field_name, block.get("default", ""))
        if isinstance(field_value, bytes):
            hex_str = field_value.hex().upper()
            display_value = field_value.decode("latin-1", errors="replace")
        elif isinstance(field_value, int):
            hex_str = f"{field_value:X}".zfill(2)
            display_value = field_value
        elif isinstance(field_value, str):
            hex_str = field_value.encode("utf-8").hex().upper()
            display_value = field_value
        else:
            hex_str = str(field_value)
            display_value = field_value

        preview_fields.append(
            PreviewField(
                name=field_name,
                value=display_value,
                hex=hex_str,
                type=block.get("type", "unknown"),
                mutable=block.get("mutable", True),
                computed=block.get("is_size_field", False),
                references=block.get("size_of") if block.get("is_size_field") else None,
                mutated=(field_name == focus_field) if focus_field else False,
            )
        )

    message_type = None
    valid_in_state = None
    causes_transition = None
    if state_model and state_model.get("transitions"):
        command_value = fields_dict.get("command")
        if command_value is not None:
            for block in blocks:
                if block.get("name") == "command" and "values" in block:
                    message_type = block["values"].get(command_value)
                    break
            if message_type:
                for transition in state_model.get("transitions", []):
                    if transition.get("message_type") == message_type:
                        valid_in_state = transition.get("from")
                        to_state = transition.get("to")
                        causes_transition = f"{valid_in_state} → {to_state}"
                        break

    return TestCasePreview(
        id=preview_id,
        mode=mode,
        mutation_type=mutation_type,
        mutators_used=mutators_used or [],
        description=description,
        focus_field=focus_field,
        hex_dump=data.hex().upper(),
        total_bytes=len(data),
        fields=preview_fields,
        message_type=message_type,
        valid_in_state=valid_in_state,
        causes_transition=causes_transition,
    )


def _get_mutator_description(mutator_name: str) -> str:
    descriptions = {
        "bitflip": "Bit flipping: Randomly flips individual bits in the message, potentially breaking field boundaries and creating invalid values",
        "byteflip": "Byte flipping: Replaces random bytes with random values, ignoring protocol structure",
        "arithmetic": "Arithmetic: Adds/subtracts small integers to 4-byte sequences, may corrupt length fields or counters",
        "interesting": "Interesting values: Injects boundary values (0, 255, 65535, etc.) at random positions",
        "havoc": "Havoc: Aggressive random mutations including insertions, deletions, and bit flips throughout the message",
        "splice": "Splice: Combines portions of two seeds to merge states or features",
    }
    return descriptions.get(mutator_name, f"Byte-level mutation: {mutator_name}")


def _detect_mutated_field(original: bytes, mutated: bytes, parser: ProtocolParser, blocks: List[dict]) -> Optional[str]:
    try:
        original_fields = parser.parse(original)
        mutated_fields = parser.parse(mutated)
        for block in blocks:
            name = block["name"]
            if name in original_fields and name in mutated_fields:
                if block.get("is_size_field"):
                    continue
                if original_fields[name] != mutated_fields[name]:
                    return name
    except Exception:  # pragma: no cover - best effort
        pass
    return None


def _build_state_machine_info(plugin: ProtocolPlugin) -> Optional[StateMachineInfo]:
    state_model = plugin.state_model
    if not state_model:
        return StateMachineInfo(has_state_model=False)

    transitions_list = state_model.get("transitions", [])
    if not transitions_list:
        return StateMachineInfo(has_state_model=False)

    message_type_to_command = {}
    for block in plugin.data_model.get("blocks", []):
        if block.get("name") == "command" and "values" in block:
            for cmd_value, cmd_name in block["values"].items():
                message_type_to_command[cmd_name] = cmd_value
            break

    transitions = [
        StateTransition(
            **{
                "from": trans.get("from"),
                "to": trans.get("to"),
                "message_type": trans.get("message_type"),
                "trigger": trans.get("trigger"),
                "expected_response": trans.get("expected_response"),
            }
        )
        for trans in transitions_list
    ]

    return StateMachineInfo(
        has_state_model=True,
        initial_state=state_model.get("initial_state"),
        states=state_model.get("states", []),
        transitions=transitions,
        message_type_to_command=message_type_to_command,
    )


# ============================================================================
# Plugin Validation Endpoint
# ============================================================================


@router.get("/plugins/{plugin_name}/validate")
async def validate_plugin_endpoint(
    plugin_name: str,
    plugin_manager=Depends(get_plugin_manager),
):
    """
    Validate a protocol plugin for errors and warnings.

    Performs static analysis to catch:
    - Missing or invalid fields
    - Broken references (size_of, etc.)
    - Unparseable seeds
    - State machine issues
    - Best practice violations
    """
    try:
        plugin = plugin_manager.load_plugin(plugin_name)
        result = validate_plugin(plugin.data_model, plugin.state_model)

        logger.info(
            "plugin_validated",
            plugin=plugin_name,
            valid=result.is_valid,
            errors=len(result.errors),
            warnings=len(result.warnings),
        )

        return result.to_dict()

    except Exception as e:
        logger.error("plugin_validation_failed", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")


# ============================================================================
# Live Packet Parser Endpoint
# ============================================================================


class PacketParseRequest(BaseModel):
    """Request to parse a packet"""

    packet: str  # Hex string, base64, or text
    format: str = "hex"  # "hex", "base64", or "text"


class ParsedField(BaseModel):
    """A parsed field from a packet"""

    name: str
    value: Any
    hex: str
    offset: int
    size: int
    type: str


class PacketParseResponse(BaseModel):
    """Response from packet parsing"""

    success: bool
    total_bytes: int
    fields: List[ParsedField]
    warnings: List[str] = []
    error: Optional[str] = None


@router.post("/plugins/{plugin_name}/parse", response_model=PacketParseResponse)
async def parse_packet_endpoint(
    plugin_name: str,
    request: PacketParseRequest,
    plugin_manager=Depends(get_plugin_manager),
):
    """
    Parse a raw packet according to the protocol data_model.

    Useful for:
    - Debugging field offsets and sizes
    - Understanding how the parser interprets real data
    - Validating that manual seeds match expectations
    """
    try:
        plugin = plugin_manager.load_plugin(plugin_name)

        # Decode packet based on format
        try:
            if request.format == "hex":
                # Remove spaces and convert hex to bytes
                hex_str = request.packet.replace(" ", "").replace("\n", "")
                packet_bytes = bytes.fromhex(hex_str)
            elif request.format == "base64":
                packet_bytes = base64.b64decode(request.packet)
            elif request.format == "text":
                packet_bytes = request.packet.encode("utf-8")
            else:
                raise HTTPException(status_code=400, detail=f"Invalid format: {request.format}")
        except Exception as e:
            return PacketParseResponse(
                success=False, total_bytes=0, fields=[], error=f"Failed to decode packet: {str(e)}"
            )

        # Denormalize data_model to get bytes back
        denormalized_model = denormalize_data_model_from_json(plugin.data_model)
        parser = ProtocolParser(denormalized_model)

        # Parse the packet
        try:
            parsed_fields_dict = parser.parse(packet_bytes)

            # Build response with field offsets
            fields = []
            offset = 0
            blocks = denormalized_model.get("blocks", [])

            for block in blocks:
                field_name = block["name"]
                field_type = block["type"]
                value = parsed_fields_dict.get(field_name)

                # Calculate size
                if field_type == "bytes":
                    if isinstance(value, bytes):
                        size = len(value)
                    else:
                        size = block.get("size", 0)
                elif field_type.startswith("uint") or field_type.startswith("int"):
                    # Determine integer size
                    if field_type.endswith("8"):
                        size = 1
                    elif field_type.endswith("16"):
                        size = 2
                    elif field_type.endswith("32"):
                        size = 4
                    elif field_type.endswith("64"):
                        size = 8
                    else:
                        size = 0
                elif field_type == "string":
                    if isinstance(value, str):
                        size = len(value.encode("utf-8"))
                    else:
                        size = 0
                else:
                    size = 0

                # Extract hex for this field
                if offset + size <= len(packet_bytes):
                    field_bytes = packet_bytes[offset : offset + size]
                    field_hex = field_bytes.hex()
                else:
                    field_hex = ""

                # Format value for display
                display_value = value
                if isinstance(value, bytes):
                    # Try to decode as string, otherwise show hex
                    try:
                        display_value = value.decode("utf-8")
                    except:
                        display_value = value.hex()

                fields.append(
                    ParsedField(
                        name=field_name,
                        value=display_value,
                        hex=field_hex,
                        offset=offset,
                        size=size,
                        type=field_type,
                    )
                )

                offset += size

            # Check for unparsed bytes
            warnings = []
            if offset < len(packet_bytes):
                warnings.append(f"{len(packet_bytes) - offset} trailing bytes not parsed")

            logger.info(
                "packet_parsed",
                plugin=plugin_name,
                total_bytes=len(packet_bytes),
                fields=len(fields),
                warnings=len(warnings),
            )

            return PacketParseResponse(
                success=True, total_bytes=len(packet_bytes), fields=fields, warnings=warnings
            )

        except Exception as e:
            logger.error("packet_parse_failed", plugin=plugin_name, error=str(e))
            return PacketParseResponse(success=False, total_bytes=len(packet_bytes), fields=[], error=str(e))

    except Exception as e:
        logger.error("parse_endpoint_failed", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Parse failed: {str(e)}")


# ============================================================================
# Mutation Workbench Endpoints
# ============================================================================


class BuildRequest(BaseModel):
    """Request to build/serialize packet from fields"""

    fields: Dict[str, Any]  # Field name -> value mapping


class BuildResponse(BaseModel):
    """Response from packet building"""

    success: bool
    hex_data: str
    total_bytes: int
    error: Optional[str] = None


@router.post("/plugins/{plugin_name}/build", response_model=BuildResponse)
async def build_packet_endpoint(
    plugin_name: str,
    request: BuildRequest,
    plugin_manager=Depends(get_plugin_manager),
):
    """
    Build/serialize a packet from field values using the protocol parser.

    This is the inverse of the parse endpoint - takes a dictionary of field
    values and produces binary data according to the data_model.

    Auto-updates dependent fields like size_of before serialization.
    """
    try:
        plugin = plugin_manager.load_plugin(plugin_name)

        # Denormalize data_model to get bytes back
        denormalized_model = denormalize_data_model_from_json(plugin.data_model)
        parser = ProtocolParser(denormalized_model)

        # Serialize the fields
        try:
            # Convert string values to bytes for bytes-type fields
            serializable_fields = {}
            blocks = denormalized_model.get("blocks", [])
            for block in blocks:
                field_name = block["name"]
                field_type = block["type"]
                value = request.fields.get(field_name)

                if value is not None:
                    # Convert string to bytes for bytes fields
                    if field_type == "bytes" and isinstance(value, str):
                        value = value.encode("utf-8")
                    serializable_fields[field_name] = value

            packet_bytes = parser.serialize(serializable_fields)
            hex_data = packet_bytes.hex().upper()

            logger.info(
                "packet_built",
                plugin=plugin_name,
                total_bytes=len(packet_bytes),
                fields=len(request.fields),
            )

            return BuildResponse(
                success=True,
                hex_data=hex_data,
                total_bytes=len(packet_bytes),
            )

        except Exception as e:
            logger.error("packet_build_failed", plugin=plugin_name, error=str(e))
            return BuildResponse(
                success=False,
                hex_data="",
                total_bytes=0,
                error=str(e),
            )

    except Exception as e:
        logger.error("build_endpoint_failed", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Build failed: {str(e)}")


class MutateRequest(BaseModel):
    """Request to apply a specific mutator"""

    seed_index: int = 0  # Which seed to use (default: first seed)
    mutator: str  # Mutator name: bitflip, byteflip, arithmetic, interesting, havoc, splice, structure_aware


class MutateResponse(BaseModel):
    """Response from mutation"""

    success: bool
    original_hex: str
    mutated_hex: str
    mutator_used: str
    original_bytes: int
    mutated_bytes: int
    fields: List[ParsedField] = []  # Parsed fields of mutated data
    error: Optional[str] = None


@router.post("/plugins/{plugin_name}/mutate_with", response_model=MutateResponse)
async def mutate_with_endpoint(
    plugin_name: str,
    request: MutateRequest,
    plugin_manager=Depends(get_plugin_manager),
):
    """
    Apply a specific mutator to a seed and return the mutated packet.

    Useful for the Mutation Workbench to test individual mutators.
    """
    try:
        plugin = plugin_manager.load_plugin(plugin_name)

        # Denormalize data_model to get seeds
        denormalized_model = denormalize_data_model_from_json(plugin.data_model)
        seeds = denormalized_model.get("seeds", [])

        if not seeds:
            raise HTTPException(status_code=400, detail="Plugin has no seeds")

        if request.seed_index < 0 or request.seed_index >= len(seeds):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid seed_index {request.seed_index} (plugin has {len(seeds)} seeds)",
            )

        seed = seeds[request.seed_index]

        # Get the appropriate mutator
        mutator_name = request.mutator.lower()

        try:
            if mutator_name == "structure_aware":
                from core.engine.structure_mutators import StructureAwareMutator

                mutator = StructureAwareMutator(denormalized_model)
                mutated = mutator.mutate(seed)
            elif mutator_name == "bitflip":
                mutator = BitFlipMutator()
                mutated = mutator.mutate(seed)
            elif mutator_name == "byteflip":
                mutator = ByteFlipMutator()
                mutated = mutator.mutate(seed)
            elif mutator_name == "arithmetic":
                mutator = ArithmeticMutator()
                mutated = mutator.mutate(seed)
            elif mutator_name == "interesting":
                mutator = InterestingValueMutator()
                mutated = mutator.mutate(seed)
            elif mutator_name == "havoc":
                mutator = HavocMutator()
                mutated = mutator.mutate(seed)
            elif mutator_name == "splice":
                if len(seeds) < 2:
                    raise HTTPException(
                        status_code=400,
                        detail="Splice mutator requires at least 2 seeds",
                    )
                mutator = SpliceMutator(seeds)
                mutated = mutator.mutate(seed)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown mutator: {mutator_name}. Valid: bitflip, byteflip, arithmetic, interesting, havoc, splice, structure_aware",
                )

            # Parse the mutated data to show fields
            parser = ProtocolParser(denormalized_model)
            try:
                parsed_fields_dict = parser.parse(mutated)
                blocks = denormalized_model.get("blocks", [])

                fields = []
                offset = 0
                for block in blocks:
                    field_name = block["name"]
                    field_type = block["type"]
                    value = parsed_fields_dict.get(field_name)

                    # Calculate size
                    if field_type == "bytes":
                        size = len(value) if isinstance(value, bytes) else block.get("size", 0)
                    elif field_type.startswith("uint") or field_type.startswith("int"):
                        if field_type.endswith("8"):
                            size = 1
                        elif field_type.endswith("16"):
                            size = 2
                        elif field_type.endswith("32"):
                            size = 4
                        elif field_type.endswith("64"):
                            size = 8
                        else:
                            size = 0
                    elif field_type == "string":
                        size = len(value.encode("utf-8")) if isinstance(value, str) else 0
                    else:
                        size = 0

                    # Extract hex for this field
                    if offset + size <= len(mutated):
                        field_bytes = mutated[offset : offset + size]
                        field_hex = field_bytes.hex()
                    else:
                        field_hex = ""

                    # Format value for display
                    display_value = value
                    if isinstance(value, bytes):
                        try:
                            display_value = value.decode("utf-8")
                        except:
                            display_value = value.hex()

                    fields.append(
                        ParsedField(
                            name=field_name,
                            value=display_value,
                            hex=field_hex,
                            offset=offset,
                            size=size,
                            type=field_type,
                        )
                    )

                    offset += size

            except Exception as e:
                logger.warning("mutated_parse_failed", error=str(e))
                fields = []

            logger.info(
                "packet_mutated",
                plugin=plugin_name,
                mutator=mutator_name,
                original_bytes=len(seed),
                mutated_bytes=len(mutated),
            )

            return MutateResponse(
                success=True,
                original_hex=seed.hex().upper(),
                mutated_hex=mutated.hex().upper(),
                mutator_used=mutator_name,
                original_bytes=len(seed),
                mutated_bytes=len(mutated),
                fields=fields,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("mutation_failed", plugin=plugin_name, mutator=mutator_name, error=str(e))
            return MutateResponse(
                success=False,
                original_hex=seed.hex().upper(),
                mutated_hex="",
                mutator_used=mutator_name,
                original_bytes=len(seed),
                mutated_bytes=0,
                error=str(e),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("mutate_endpoint_failed", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Mutation failed: {str(e)}")


class FieldMutateRequest(BaseModel):
    """Request to apply mutation to a specific field"""

    seed_index: int = 0
    field_name: str  # Target field to mutate
    mutator: str  # For byte-level: bitflip, byteflip, arithmetic, interesting
    strategy: Optional[str] = None  # For structure-aware: boundary_values, expand_field, etc.


class FieldMutateResponse(BaseModel):
    """Response from field mutation"""

    success: bool
    original_hex: str
    mutated_hex: str
    field_name: str
    mutator_used: str
    strategy_used: Optional[str] = None
    original_bytes: int
    mutated_bytes: int
    fields: List[ParsedField] = []
    error: Optional[str] = None


@router.post("/plugins/{plugin_name}/mutate_field", response_model=FieldMutateResponse)
async def mutate_field_endpoint(
    plugin_name: str,
    request: FieldMutateRequest,
    plugin_manager=Depends(get_plugin_manager),
):
    """
    Apply mutation to a specific field.

    For structure-aware mutations, applies the specified strategy to the field.
    For byte-level mutations, constrains mutation to the field's byte range.
    """
    try:
        plugin = plugin_manager.load_plugin(plugin_name)
        denormalized_model = denormalize_data_model_from_json(plugin.data_model)
        seeds = denormalized_model.get("seeds", [])

        if not seeds:
            raise HTTPException(status_code=400, detail="Plugin has no seeds")

        if request.seed_index < 0 or request.seed_index >= len(seeds):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid seed_index {request.seed_index}",
            )

        seed = seeds[request.seed_index]
        mutator_name = request.mutator.lower()

        # Parse original seed to get field info
        parser = ProtocolParser(denormalized_model)
        original_fields = parser.parse(seed)
        blocks = denormalized_model.get("blocks", [])

        # Find target field block
        target_block = None
        for block in blocks:
            if block["name"] == request.field_name:
                target_block = block
                break

        if not target_block:
            raise HTTPException(
                status_code=400,
                detail=f"Field '{request.field_name}' not found in protocol",
            )

        # Determine if this is structure-aware or byte-level
        if mutator_name == "structure_aware" or request.strategy:
            # Structure-aware mutation on specific field
            from core.engine.structure_mutators import StructureAwareMutator

            mutator = StructureAwareMutator(denormalized_model)

            # Use provided strategy or pick one
            if request.strategy:
                strategy = request.strategy
            else:
                # Default to boundary_values
                strategy = "boundary_values"

            # Apply mutation to specific field
            try:
                mutated_fields = original_fields.copy()
                mutated_value = mutator._apply_strategy(
                    strategy,
                    original_fields[request.field_name],
                    target_block
                )
                mutated_fields[request.field_name] = mutated_value
                mutated = parser.serialize(mutated_fields)
                strategy_used = strategy
            except Exception as e:
                logger.error("field_mutation_failed", field=request.field_name, strategy=strategy, error=str(e))
                raise HTTPException(status_code=400, detail=f"Mutation failed: {str(e)}")

        else:
            # Byte-level mutation scoped to field
            # Get field offset and size
            offset = 0
            field_size = 0

            for block in blocks:
                field_name = block["name"]
                field_type = block["type"]

                if field_name == request.field_name:
                    # Found target field, calculate its size
                    value = original_fields.get(field_name)
                    if field_type == "bytes":
                        field_size = len(value) if isinstance(value, bytes) else block.get("size", 0)
                    elif field_type.startswith("uint") or field_type.startswith("int"):
                        if field_type.endswith("8"):
                            field_size = 1
                        elif field_type.endswith("16"):
                            field_size = 2
                        elif field_type.endswith("32"):
                            field_size = 4
                        elif field_type.endswith("64"):
                            field_size = 8
                    elif field_type == "string":
                        field_size = len(value.encode("utf-8")) if isinstance(value, str) else 0
                    break
                else:
                    # Accumulate offset
                    value = original_fields.get(field_name)
                    if field_type == "bytes":
                        offset += len(value) if isinstance(value, bytes) else block.get("size", 0)
                    elif field_type.startswith("uint") or field_type.startswith("int"):
                        if field_type.endswith("8"):
                            offset += 1
                        elif field_type.endswith("16"):
                            offset += 2
                        elif field_type.endswith("32"):
                            offset += 4
                        elif field_type.endswith("64"):
                            offset += 8
                    elif field_type == "string":
                        offset += len(value.encode("utf-8")) if isinstance(value, str) else 0

            if field_size == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not determine size of field '{request.field_name}'",
                )

            # Extract field bytes, mutate, reassemble
            before = seed[:offset]
            field_bytes = seed[offset:offset + field_size]
            after = seed[offset + field_size:]

            # Apply byte-level mutator to field bytes only
            if mutator_name == "bitflip":
                mutator = BitFlipMutator()
            elif mutator_name == "byteflip":
                mutator = ByteFlipMutator()
            elif mutator_name == "arithmetic":
                mutator = ArithmeticMutator()
            elif mutator_name == "interesting":
                mutator = InterestingValueMutator()
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported byte-level mutator for field mutation: {mutator_name}. Valid: bitflip, byteflip, arithmetic, interesting",
                )

            mutated_field_bytes = mutator.mutate(field_bytes)
            mutated = before + mutated_field_bytes + after
            strategy_used = None

        # Parse mutated packet to show fields
        try:
            parsed_fields_dict = parser.parse(mutated)

            fields = []
            offset = 0
            for block in blocks:
                field_name = block["name"]
                field_type = block["type"]
                value = parsed_fields_dict.get(field_name)

                # Calculate size
                if field_type == "bytes":
                    size = len(value) if isinstance(value, bytes) else block.get("size", 0)
                elif field_type.startswith("uint") or field_type.startswith("int"):
                    if field_type.endswith("8"):
                        size = 1
                    elif field_type.endswith("16"):
                        size = 2
                    elif field_type.endswith("32"):
                        size = 4
                    elif field_type.endswith("64"):
                        size = 8
                    else:
                        size = 0
                elif field_type == "string":
                    size = len(value.encode("utf-8")) if isinstance(value, str) else 0
                else:
                    size = 0

                # Extract hex for this field
                if offset + size <= len(mutated):
                    field_bytes = mutated[offset:offset + size]
                    field_hex = field_bytes.hex()
                else:
                    field_hex = ""

                # Format value for display
                display_value = value
                if isinstance(value, bytes):
                    try:
                        display_value = value.decode("utf-8")
                    except:
                        display_value = value.hex()

                fields.append(
                    ParsedField(
                        name=field_name,
                        value=display_value,
                        hex=field_hex,
                        offset=offset,
                        size=size,
                        type=field_type,
                    )
                )

                offset += size

        except Exception as e:
            logger.warning("mutated_field_parse_failed", error=str(e))
            fields = []

        logger.info(
            "field_mutated",
            plugin=plugin_name,
            field=request.field_name,
            mutator=mutator_name,
            strategy=strategy_used,
        )

        return FieldMutateResponse(
            success=True,
            original_hex=seed.hex().upper(),
            mutated_hex=mutated.hex().upper(),
            field_name=request.field_name,
            mutator_used=mutator_name,
            strategy_used=strategy_used,
            original_bytes=len(seed),
            mutated_bytes=len(mutated),
            fields=fields,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("field_mutate_endpoint_failed", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Field mutation failed: {str(e)}")
