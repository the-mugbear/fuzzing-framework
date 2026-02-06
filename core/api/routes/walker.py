"""State Machine Walker API endpoints."""
import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

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


def _get_message_type(transition: dict) -> str:
    """
    Get message type from a transition, handling both 'message_type' and 'message' keys.

    Some plugins use 'message_type' (standard), others use 'message' (shorthand).
    """
    return transition.get("message_type") or transition.get("message") or transition.get("trigger")

# Configuration
MAX_EXECUTION_HISTORY_PER_SESSION = 1000  # Limit history size per session
SESSION_TTL_HOURS = 96  # Auto-cleanup sessions older than this
CLEANUP_INTERVAL_SECONDS = 300  # Run cleanup every 5 minutes
TRANSACTION_TIMEOUT_SECONDS = 30.0  # Total timeout for send/receive transaction
READ_TIMEOUT_SECONDS = 5.0  # Per-read timeout within transaction

# =============================================================================
# IN-MEMORY SESSION STORAGE
# =============================================================================
# IMPORTANT: Walker sessions are stored in process-local memory. This means:
#
# 1. Sessions do NOT survive server restarts
# 2. In multi-worker deployments (uvicorn --workers N, gunicorn), each worker
#    has its own session storage. Requests may be routed to different workers,
#    causing "session not found" errors.
#
# PRODUCTION RECOMMENDATIONS:
# - For single-worker deployments: Current implementation works fine
# - For multi-worker deployments: Consider one of:
#   a) Use sticky sessions (route by session_id to same worker)
#   b) Replace with Redis/Memcached for shared session storage
#   c) Run walker API on a dedicated single-worker service
#
# The fuzzing sessions (FuzzSession) use SQLite persistence and don't have
# this limitation. Only the State Walker feature is affected.
# =============================================================================

_walker_sessions: Dict[str, StatefulFuzzingSession] = {}
_session_protocols: Dict[str, str] = {}  # Maps session_id -> protocol_name
_execution_history: Dict[str, list] = {}  # Maps session_id -> list of execution results
_response_planners: Dict[str, ResponsePlanner] = {}  # Maps session_id -> ResponsePlanner
_field_overrides: Dict[str, Dict[str, Any]] = {}  # Maps session_id -> field overrides from response handlers

# Session metadata for cleanup
_session_metadata: Dict[str, Dict[str, datetime]] = {}  # Maps session_id -> {created_at, last_accessed_at}

# Cleanup task
_cleanup_task: asyncio.Task = None


def _record_session_access(session_id: str) -> None:
    """Update last accessed timestamp for session."""
    if session_id in _session_metadata:
        _session_metadata[session_id]["last_accessed_at"] = datetime.utcnow()


def _cleanup_stale_sessions() -> int:
    """
    Remove sessions that haven't been accessed in SESSION_TTL_HOURS.

    Returns:
        Number of sessions cleaned up
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=SESSION_TTL_HOURS)

    stale_sessions = [
        session_id
        for session_id, metadata in _session_metadata.items()
        if metadata["last_accessed_at"] < cutoff
    ]

    for session_id in stale_sessions:
        # Capture metadata before deletion for logging
        metadata = _session_metadata.get(session_id, {})
        age_hours = (now - metadata["created_at"]).total_seconds() / 3600 if metadata.get("created_at") else 0

        _delete_session_data(session_id)
        logger.info(
            "walker_session_auto_cleanup",
            session_id=session_id,
            age_hours=age_hours
        )

    return len(stale_sessions)


def _delete_session_data(session_id: str) -> None:
    """Delete all data associated with a session."""
    _walker_sessions.pop(session_id, None)
    _session_protocols.pop(session_id, None)
    _execution_history.pop(session_id, None)
    _response_planners.pop(session_id, None)
    _field_overrides.pop(session_id, None)
    _session_metadata.pop(session_id, None)


async def _cleanup_loop():
    """Background task to periodically cleanup stale sessions."""
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            cleaned = _cleanup_stale_sessions()
            if cleaned > 0:
                logger.info("walker_cleanup_completed", sessions_cleaned=cleaned)
        except Exception as e:
            logger.error("walker_cleanup_error", error=str(e))


def _start_cleanup_task():
    """Start the background cleanup task if not already running."""
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_cleanup_loop())
        logger.info("walker_cleanup_task_started", interval_seconds=CLEANUP_INTERVAL_SECONDS)


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
            message_type=_get_message_type(trans),
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
        # Start cleanup task on first walker session
        _start_cleanup_task()

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

        # Record session metadata for cleanup
        now = datetime.utcnow()
        _session_metadata[session_id] = {
            "created_at": now,
            "last_accessed_at": now,
        }

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
            ttl_hours=SESSION_TTL_HOURS,
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
        if request.transition_index < 0 or request.transition_index >= len(valid_transitions):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid transition index {request.transition_index}. Must be 0-{len(valid_transitions) - 1}"
            )

        selected_transition = valid_transitions[request.transition_index]
        message_type = _get_message_type(selected_transition)
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

        async def _execute_transaction() -> bytes:
            """Execute the send/receive transaction with per-read timeouts."""
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(request.target_host, request.target_port),
                timeout=READ_TIMEOUT_SECONDS,
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
                        chunk = await asyncio.wait_for(reader.read(4096), timeout=READ_TIMEOUT_SECONDS)
                    except asyncio.TimeoutError:
                        break
                    if not chunk:
                        break
                    response_chunks.append(chunk)
                return b"".join(response_chunks)
            finally:
                writer.close()
                await writer.wait_closed()

        try:
            # Wrap entire transaction in total timeout to prevent indefinite hangs
            response_bytes = await asyncio.wait_for(
                _execute_transaction(),
                timeout=TRANSACTION_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            success = False
            error_msg = f"Transaction timeout after {TRANSACTION_TIMEOUT_SECONDS}s"
            logger.error(
                "transition_transaction_timeout",
                session_id=request.session_id,
                timeout_seconds=TRANSACTION_TIMEOUT_SECONDS,
            )
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

        # Store in execution history with size limit
        if request.session_id not in _execution_history:
            _execution_history[request.session_id] = []

        history = _execution_history[request.session_id]
        history.append(execution_record)

        # Trim history if it exceeds max size (FIFO)
        if len(history) > MAX_EXECUTION_HISTORY_PER_SESSION:
            removed = history.pop(0)
            logger.debug(
                "execution_history_trimmed",
                session_id=request.session_id,
                removed_execution=removed.execution_number,
                max_size=MAX_EXECUTION_HISTORY_PER_SESSION
            )

        # Record session access
        _record_session_access(request.session_id)

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

        # Record session access
        _record_session_access(session_id)

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

        # Record session access
        _record_session_access(session_id)

        return _build_state_response(session_id, session)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("walker_get_state_failed", session_id=session_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to get walker state: {str(exc)}")


@router.get("/")
async def list_walker_sessions():
    """
    List all active walker sessions with metadata.

    Returns:
        List of session info including ID, protocol, age, and last access time
    """
    now = datetime.utcnow()
    sessions = []

    for session_id in _walker_sessions.keys():
        metadata = _session_metadata.get(session_id, {})
        protocol = _session_protocols.get(session_id, "unknown")
        history_count = len(_execution_history.get(session_id, []))

        created_at = metadata.get("created_at")
        last_accessed = metadata.get("last_accessed_at")

        sessions.append({
            "session_id": session_id,
            "protocol": protocol,
            "created_at": created_at.isoformat() if created_at else None,
            "last_accessed_at": last_accessed.isoformat() if last_accessed else None,
            "age_hours": (now - created_at).total_seconds() / 3600 if created_at else None,
            "idle_hours": (now - last_accessed).total_seconds() / 3600 if last_accessed else None,
            "execution_count": history_count,
        })

    return {
        "total_sessions": len(sessions),
        "sessions": sessions,
        "cleanup_config": {
            "ttl_hours": SESSION_TTL_HOURS,
            "max_history_per_session": MAX_EXECUTION_HISTORY_PER_SESSION,
            "cleanup_interval_seconds": CLEANUP_INTERVAL_SECONDS,
            "transaction_timeout_seconds": TRANSACTION_TIMEOUT_SECONDS,
        },
        "storage_note": "Sessions are process-local and won't survive restarts or multi-worker deployments.",
    }


@router.delete("/{session_id}")
async def delete_walker(session_id: str):
    """
    Delete a walker session and free resources.
    """
    if session_id in _walker_sessions:
        _delete_session_data(session_id)
        logger.info("walker_session_deleted", session_id=session_id)
        return {"status": "deleted"}

    raise HTTPException(status_code=404, detail="Walker session not found")
