"""State Machine Walker API endpoints."""
import socket
import time
import uuid
from typing import Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException

from core.api.deps import get_plugin_manager
from core.engine.stateful_fuzzer import StatefulFuzzingSession
from core.models import (
    TransitionInfo,
    WalkerExecuteRequest,
    WalkerExecuteResponse,
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

    # Extract state history (just state names)
    state_history = [entry.get("state", "") for entry in session.state_history]

    # Extract transition history (message types)
    transition_history = [entry.get("message_type", "") for entry in session.state_history]

    return WalkerStateResponse(
        session_id=session_id,
        current_state=session.current_state,
        valid_transitions=transition_infos,
        state_history=state_history,
        transition_history=transition_history,
        state_coverage=session.get_state_coverage(),
        transition_coverage=session.get_transition_coverage(),
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
        walker_session = StatefulFuzzingSession(
            state_model=plugin.state_model,
            data_model=denormalized_model,
            progression_weight=1.0,  # Always follow valid transitions
        )

        _walker_sessions[session_id] = walker_session
        _session_protocols[session_id] = request.protocol

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

        # Send the message to the target
        start_time = time.time()
        response_bytes = b""
        success = True
        error_msg = None

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5.0)
                sock.connect((request.target_host, request.target_port))
                sock.sendall(seed)

                try:
                    response_bytes = sock.recv(4096)
                except socket.timeout:
                    response_bytes = b""
        except Exception as e:
            success = False
            error_msg = str(e)
            logger.error(
                "transition_send_failed",
                session_id=request.session_id,
                error=str(e),
            )

        duration_ms = (time.time() - start_time) * 1000

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

        # Build response
        return WalkerExecuteResponse(
            success=success,
            old_state=old_state,
            new_state=new_state,
            message_type=message_type,
            sent_hex=seed.hex().upper(),
            sent_bytes=len(seed),
            response_hex=response_bytes.hex().upper() if response_bytes else None,
            response_bytes=len(response_bytes),
            duration_ms=duration_ms,
            error=error_msg,
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
        logger.info("walker_session_deleted", session_id=session_id)
        return {"status": "deleted"}

    raise HTTPException(status_code=404, detail="Walker session not found")
