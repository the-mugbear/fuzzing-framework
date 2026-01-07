"""State Machine Walker API endpoints."""
import asyncio
import time
import uuid
from datetime import datetime
from typing import Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException

from core.api.deps import get_plugin_manager
from core.engine.protocol_parser import ProtocolParser
from core.engine.response_planner import ResponsePlanner
from core.engine.stateful_fuzzer import StatefulFuzzingSession
from core.models import (
    TransitionInfo,
    WalkerExecuteRequest,
    WalkerExecuteResponse,
    WalkerExecutionRecord,
    WalkerInitRequest,
    WalkerStateResponse,
)
from core.plugin_loader import (
    PluginManager,
    decode_seeds_from_json,
    denormalize_data_model_from_json,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/walker", tags=["walker"])

# In-memory storage for walker sessions (could be moved to Redis in production)
_walker_sessions: Dict[str, StatefulFuzzingSession] = {}
_session_protocols: Dict[str, str] = {}  # Maps session_id -> protocol_name
_execution_history: Dict[str, list] = {}  # Maps session_id -> list of execution results
_response_planners: Dict[str, ResponsePlanner] = {}  # Maps session_id -> ResponsePlanner
_field_overrides: Dict[str, Dict[str, any]] = {}  # Maps session_id -> field overrides from response handlers


def _serialize_parsed_fields(fields: Dict[str, any], data_model: Dict[str, any]) -> Dict[str, any]:
    """
    Convert parsed fields to JSON-serializable format.

    Converts bytes values to hex strings for display in the UI.
    For string fields, includes both hex and decoded text.
    """
    # Build a map of field names to their block definitions
    blocks_by_name = {block['name']: block for block in data_model.get('blocks', [])}

    serialized = {}
    for key, value in fields.items():
        block = blocks_by_name.get(key, {})
        field_type = block.get('type', '')

        if isinstance(value, bytes):
            # Convert bytes to hex string with spaces for readability
            hex_str = value.hex().upper()
            hex_display = ' '.join(hex_str[i:i+2] for i in range(0, len(hex_str), 2))

            # If this is a string field, also try to decode it
            if field_type == 'string':
                encoding = block.get('encoding', 'utf-8')
                try:
                    decoded = value.decode(encoding)
                    serialized[key] = {
                        'hex': hex_display,
                        'decoded': decoded,
                        'type': 'string'
                    }
                except UnicodeDecodeError:
                    serialized[key] = {
                        'hex': hex_display,
                        'decoded': '<decode error>',
                        'type': 'string'
                    }
            else:
                # For regular bytes fields, show hex and attempt UTF-8 decode as preview
                decoded_preview = None
                try:
                    decoded_preview = value.decode('utf-8')
                    # Only include if it's printable and not too short
                    if len(decoded_preview) >= 2 and decoded_preview.isprintable():
                        serialized[key] = {
                            'hex': hex_display,
                            'decoded': decoded_preview,
                            'type': 'bytes'
                        }
                    else:
                        serialized[key] = {
                            'hex': hex_display,
                            'type': 'bytes'
                        }
                except (UnicodeDecodeError, AttributeError):
                    serialized[key] = {
                        'hex': hex_display,
                        'type': 'bytes'
                    }
        elif isinstance(value, int):
            # Show integers with their type info
            serialized[key] = {
                'value': value,
                'type': field_type if field_type else 'int'
            }
        elif isinstance(value, str):
            # Already a string (from protocol parser string handling)
            serialized[key] = {
                'decoded': value,
                'type': 'string'
            }
        else:
            serialized[key] = value
    return serialized


def _build_state_response(session_id: str, session: StatefulFuzzingSession) -> WalkerStateResponse:
    """Build a WalkerStateResponse from a StatefulFuzzingSession."""
    valid_transitions = session.get_valid_transitions()

    # Convert transitions to TransitionInfo objects
    transition_infos = [
        TransitionInfo(
            from_state=trans.get("from"),
            to_state=trans.get("to"),
            message_type=trans.get("message_type"),
            expected_response=trans.get("expected_response"),
        )
        for trans in valid_transitions
    ]

    # Build state path from initial state through all successful transitions
    state_path = []
    if session.state_history:
        # Start with the "from" state of the first transition
        first_entry = session.state_history[0]
        state_path.append(first_entry.get("from", ""))

        # Add the "to" state of each successful transition
        for entry in session.state_history:
            if entry.get("success", False) and "to" in entry:
                state_path.append(entry["to"])

    # Extract transition history (message types)
    transition_history = [entry.get("message_type", "") for entry in session.state_history]

    # Get execution history for this session
    executions = _execution_history.get(session_id, [])

    return WalkerStateResponse(
        session_id=session_id,
        current_state=session.current_state,
        valid_transitions=transition_infos,
        state_history=state_path,
        transition_history=transition_history,
        state_coverage=session.get_state_coverage(),
        transition_coverage=session.get_transition_coverage(),
        execution_history=executions,
    )


@router.post("/init", response_model=WalkerStateResponse)
async def initialize_walker(
    request: WalkerInitRequest,
    plugin_manager: PluginManager = Depends(get_plugin_manager),
):
    """
    Initialize a new state machine walker session.

    Creates a stateful fuzzing session and returns the initial state
    with available transitions.
    """
    try:
        plugin = plugin_manager.load_plugin(request.protocol)

        if not plugin.state_model:
            raise HTTPException(
                status_code=400,
                detail=f"Protocol '{request.protocol}' does not have a state model"
            )

        # Create a new walker session
        session_id = str(uuid.uuid4())
        denormalized_model = denormalize_data_model_from_json(plugin.data_model)

        # Denormalize response_model if available
        response_model = None
        if plugin.response_model:
            response_model = denormalize_data_model_from_json(plugin.response_model)

        walker_session = StatefulFuzzingSession(
            state_model=plugin.state_model,
            data_model=denormalized_model,
            response_model=response_model,
            progression_weight=1.0,  # Always follow valid transitions
        )

        _walker_sessions[session_id] = walker_session
        _session_protocols[session_id] = request.protocol
        _execution_history[session_id] = []  # Initialize empty execution history
        _field_overrides[session_id] = {}  # Initialize empty field overrides

        # Create response planner if protocol has response handlers
        if plugin.response_handlers:
            response_planner = ResponsePlanner(
                request_model=denormalized_model,
                response_model=response_model,
                handlers=plugin.response_handlers,
            )
            _response_planners[session_id] = response_planner
            logger.info(
                "response_planner_initialized",
                session_id=session_id,
                handler_count=len(plugin.response_handlers)
            )

        logger.info(
            "walker_session_initialized",
            session_id=session_id,
            protocol=request.protocol,
            initial_state=walker_session.current_state,
        )

        return _build_state_response(session_id, walker_session)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("walker_init_failed", protocol=request.protocol, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to initialize walker: {str(exc)}")


@router.post("/execute", response_model=WalkerExecuteResponse)
async def execute_transition(
    request: WalkerExecuteRequest,
    plugin_manager: PluginManager = Depends(get_plugin_manager),
):
    """
    Execute a state transition by sending the corresponding message.

    This will:
    1. Get the selected transition
    2. Find a seed for that message type
    3. Send it to the target
    4. Update the walker state
    5. Return the new state with available transitions
    """
    try:
        # Get the walker session
        session = _walker_sessions.get(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Walker session not found")

        # Get the protocol for this session
        protocol_name = _session_protocols.get(request.session_id)
        if not protocol_name:
            raise HTTPException(status_code=500, detail="Protocol not found for session")

        # Load the plugin to get seeds
        plugin = plugin_manager.load_plugin(protocol_name)
        denormalized_model = denormalize_data_model_from_json(plugin.data_model)
        seeds = decode_seeds_from_json(plugin.data_model.get("seeds", []))

        # Get valid transitions
        valid_transitions = session.get_valid_transitions()
        if request.transition_index >= len(valid_transitions):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid transition index {request.transition_index}"
            )

        selected_transition = valid_transitions[request.transition_index]
        message_type = selected_transition.get("message_type")
        old_state = session.current_state

        logger.info(
            "executing_transition",
            session_id=request.session_id,
            from_state=old_state,
            to_state=selected_transition.get("to"),
            message_type=message_type,
        )

        # Find a seed for this message type
        seed = session.find_seed_for_message_type(message_type, seeds)
        if not seed:
            raise HTTPException(
                status_code=400,
                detail=f"No seed found for message type '{message_type}'"
            )

        # Apply field overrides from response handlers if any
        overrides = _field_overrides.get(request.session_id, {})
        if overrides:
            try:
                # Parse the seed
                request_parser = ProtocolParser(denormalized_model)
                fields = request_parser.parse(seed)

                # Apply overrides
                fields.update(overrides)

                # Serialize back to bytes
                seed = request_parser.serialize(fields)

                logger.info(
                    "field_overrides_applied",
                    session_id=request.session_id,
                    overrides=list(overrides.keys())
                )
            except Exception as e:
                logger.warning(
                    "field_override_failed",
                    session_id=request.session_id,
                    error=str(e)
                )

        # Send the message to the target
        start_time = time.time()
        response_bytes = b""
        success = True
        error_msg = None
        timeout = 5.0

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(request.target_host, request.target_port),
                timeout=timeout,
            )
            try:
                writer.write(seed)
                await writer.drain()
                try:
                    writer.write_eof()
                except (AttributeError, RuntimeError):
                    pass

                response_chunks = []
                while True:
                    try:
                        chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
                    except asyncio.TimeoutError:
                        break
                    if not chunk:
                        break
                    response_chunks.append(chunk)
                response_bytes = b"".join(response_chunks)
            finally:
                writer.close()
                await writer.wait_closed()
        except Exception as e:
            success = False
            error_msg = str(e)
            logger.error(
                "transition_send_failed",
                session_id=request.session_id,
                error=str(e),
            )

        duration_ms = (time.time() - start_time) * 1000

        # Process response with response handlers to extract field overrides
        if success and response_bytes:
            planner = _response_planners.get(request.session_id)
            if planner:
                try:
                    # Parse the response
                    parsed_response = planner.response_parser.parse(response_bytes)

                    new_overrides, matched_handlers = planner.extract_overrides(parsed_response)

                    for handler in matched_handlers:
                        logger.info(
                            "response_handler_matched",
                            session_id=request.session_id,
                            handler=handler.get("name"),
                            fields_updated=list((handler.get("set_fields") or {}).keys()),
                        )

                    # Update field overrides for next message
                    if new_overrides:
                        _field_overrides[request.session_id].update(new_overrides)
                        logger.info(
                            "field_overrides_updated",
                            session_id=request.session_id,
                            overrides=list(new_overrides.keys())
                        )

                except Exception as e:
                    logger.warning(
                        "response_handler_processing_failed",
                        session_id=request.session_id,
                        error=str(e)
                    )

        # Validate response using protocol validator (logic oracle)
        validation_passed = None
        validation_error = None
        if success and response_bytes:
            validator = plugin_manager.get_validator(protocol_name)
            if validator:
                try:
                    validation_passed = validator(response_bytes)
                    if not validation_passed:
                        logger.info(
                            "response_validation_failed",
                            session_id=request.session_id,
                            message_type=message_type
                        )
                except Exception as e:
                    validation_error = str(e)
                    logger.warning(
                        "response_validator_error",
                        session_id=request.session_id,
                        error=str(e)
                    )

        # Update walker state based on transition
        execution_result = "pass" if success else "error"
        session.update_state(
            sent_message=seed,
            response=response_bytes,
            execution_result=execution_result,
        )

        new_state = session.current_state

        logger.info(
            "transition_executed",
            session_id=request.session_id,
            old_state=old_state,
            new_state=new_state,
            success=success,
        )

        # Parse sent and received data for display
        sent_parsed = None
        response_parsed = None

        try:
            # Parse sent message using data_model
            request_parser = ProtocolParser(denormalized_model)
            sent_parsed = request_parser.parse(seed)

            # Convert bytes values to hex strings for JSON serialization
            sent_parsed = _serialize_parsed_fields(sent_parsed, denormalized_model)
        except Exception as e:
            logger.warning("failed_to_parse_sent_data", error=str(e))

        try:
            # Parse response using response_model if available
            if response_bytes and plugin.response_model:
                # Denormalize response_model just like data_model
                denormalized_response_model = denormalize_data_model_from_json(plugin.response_model)
                response_parser = ProtocolParser(denormalized_response_model)
                response_parsed = response_parser.parse(response_bytes)

                # Convert bytes values to hex strings for JSON serialization
                response_parsed = _serialize_parsed_fields(response_parsed, denormalized_response_model)
        except Exception as e:
            logger.warning("failed_to_parse_response_data", error=str(e))

        # Create execution record for history
        execution_number = len(_execution_history.get(request.session_id, [])) + 1
        execution_record = WalkerExecutionRecord(
            execution_number=execution_number,
            success=success,
            old_state=old_state,
            new_state=new_state,
            message_type=message_type,
            sent_hex=seed.hex().upper(),
            sent_bytes=len(seed),
            sent_parsed=sent_parsed,
            response_hex=response_bytes.hex().upper() if response_bytes else None,
            response_bytes=len(response_bytes),
            response_parsed=response_parsed,
            duration_ms=duration_ms,
            error=error_msg,
            validation_passed=validation_passed,
            validation_error=validation_error,
            timestamp=datetime.utcnow().isoformat(),
        )

        # Store in execution history
        if request.session_id not in _execution_history:
            _execution_history[request.session_id] = []
        _execution_history[request.session_id].append(execution_record)

        # Build response
        return WalkerExecuteResponse(
            success=success,
            old_state=old_state,
            new_state=new_state,
            message_type=message_type,
            sent_hex=seed.hex().upper(),
            sent_bytes=len(seed),
            sent_parsed=sent_parsed,
            response_hex=response_bytes.hex().upper() if response_bytes else None,
            response_bytes=len(response_bytes),
            response_parsed=response_parsed,
            duration_ms=duration_ms,
            error=error_msg,
            validation_passed=validation_passed,
            validation_error=validation_error,
            current_state=_build_state_response(request.session_id, session),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("walker_execute_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to execute transition: {str(exc)}")


@router.post("/{session_id}/reset", response_model=WalkerStateResponse)
async def reset_walker(session_id: str):
    """
    Reset a walker session to its initial state.

    Clears history and coverage stats.
    """
    try:
        session = _walker_sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Walker session not found")

        session.reset_to_initial_state()

        # Clear field overrides on reset
        if session_id in _field_overrides:
            _field_overrides[session_id] = {}

        logger.info("walker_session_reset", session_id=session_id)

        return _build_state_response(session_id, session)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("walker_reset_failed", session_id=session_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to reset walker: {str(exc)}")


@router.get("/{session_id}", response_model=WalkerStateResponse)
async def get_walker_state(session_id: str):
    """
    Get the current state of a walker session.
    """
    try:
        session = _walker_sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Walker session not found")

        return _build_state_response(session_id, session)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("walker_get_state_failed", session_id=session_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to get walker state: {str(exc)}")


@router.delete("/{session_id}")
async def delete_walker(session_id: str):
    """
    Delete a walker session and free resources.
    """
    if session_id in _walker_sessions:
        del _walker_sessions[session_id]

        # Clean up associated data
        if session_id in _session_protocols:
            del _session_protocols[session_id]
        if session_id in _execution_history:
            del _execution_history[session_id]
        if session_id in _response_planners:
            del _response_planners[session_id]
        if session_id in _field_overrides:
            del _field_overrides[session_id]

        logger.info("walker_session_deleted", session_id=session_id)
        return {"status": "deleted"}

    raise HTTPException(status_code=404, detail="Walker session not found")
