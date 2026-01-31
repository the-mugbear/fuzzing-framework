"""Orchestration endpoints for context, stages, connections, heartbeat, and replay.

These endpoints support orchestrated sessions with multi-stage protocols,
persistent connections, and context-based message serialization.
"""
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException

from core.api.deps import get_orchestrator, get_plugin_manager
from core.models import (
    ConnectionInfo,
    ConnectionStatusResponse,
    ContextSetRequest,
    ContextSnapshotResponse,
    ContextValueResponse,
    HeartbeatStatusResponse,
    OrchestratedReplayRequest,
    OrchestratedReplayResponse,
    OrchestratedReplayResult,
    StageInfo,
    StageListResponse,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/sessions", tags=["orchestration"])


# --------------------------------------------------------------------------
# Context Endpoints
# --------------------------------------------------------------------------


@router.get("/{session_id}/context", response_model=ContextSnapshotResponse)
async def get_context(session_id: str, orchestrator=Depends(get_orchestrator)):
    """
    Get the full context snapshot for a session.

    Returns all context values, bootstrap status, and key count.
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get context from orchestrator's context registry
    context = _get_session_context(orchestrator, session_id)
    if not context:
        return ContextSnapshotResponse(
            session_id=session_id,
            values={},
            bootstrap_complete=False,
            key_count=0,
        )

    snapshot = context.snapshot()
    return ContextSnapshotResponse(
        session_id=session_id,
        values=snapshot.get("values", {}),
        bootstrap_complete=snapshot.get("bootstrap_complete", False),
        key_count=len(snapshot.get("values", {})),
    )


@router.get("/{session_id}/context/{key}", response_model=ContextValueResponse)
async def get_context_value(session_id: str, key: str, orchestrator=Depends(get_orchestrator)):
    """
    Get a single context value by key.

    Returns the value, its type, and the key name.
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    context = _get_session_context(orchestrator, session_id)
    if not context or not context.has(key):
        raise HTTPException(
            status_code=404,
            detail=f"Context key '{key}' not found. Available keys: {context.keys() if context else []}",
        )

    value = context.get(key)
    return ContextValueResponse(
        key=key,
        value=value,
        value_type=type(value).__name__,
    )


@router.post("/{session_id}/context", response_model=ContextValueResponse)
async def set_context_value(
    session_id: str,
    request: ContextSetRequest,
    orchestrator=Depends(get_orchestrator),
):
    """
    Set a context value.

    Use this to inject values for testing or to override extracted values.
    Supports strings, numbers, and hex-encoded bytes (prefix with '0x').
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    context = _get_or_create_session_context(orchestrator, session_id)

    # Handle hex-encoded bytes
    value = request.value
    if isinstance(value, str) and value.startswith("0x"):
        try:
            value = bytes.fromhex(value[2:])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid hex string")

    context.set(request.key, value)
    logger.info("context_value_set_via_api", session_id=session_id, key=request.key)

    return ContextValueResponse(
        key=request.key,
        value=value,
        value_type=type(value).__name__,
    )


@router.delete("/{session_id}/context/{key}")
async def delete_context_value(session_id: str, key: str, orchestrator=Depends(get_orchestrator)):
    """
    Delete a context value by key.
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    context = _get_session_context(orchestrator, session_id)
    if not context:
        raise HTTPException(status_code=404, detail="No context for session")

    if not context.delete(key):
        raise HTTPException(status_code=404, detail=f"Context key '{key}' not found")

    logger.info("context_value_deleted_via_api", session_id=session_id, key=key)
    return {"status": "deleted", "key": key}


# --------------------------------------------------------------------------
# Stage Endpoints
# --------------------------------------------------------------------------


@router.get("/{session_id}/stages", response_model=StageListResponse)
async def list_stages(
    session_id: str,
    orchestrator=Depends(get_orchestrator),
    plugin_manager=Depends(get_plugin_manager),
):
    """
    List protocol stages and their status.

    Returns bootstrap, fuzz_target, and teardown stages with execution status.
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get protocol stack from plugin
    protocol_stack = plugin_manager.get_protocol_stack(session.protocol)
    if not protocol_stack:
        # Simple protocol without stages
        return StageListResponse(
            session_id=session_id,
            stages=[
                StageInfo(
                    name="application",
                    role="fuzz_target",
                    status="active",
                )
            ],
            bootstrap_complete=True,
        )

    # Get stage status from stage runner
    stage_runner = _get_stage_runner(orchestrator, session_id)
    stage_statuses = {}
    if stage_runner:
        for status in stage_runner.get_stage_statuses():
            stage_statuses[status.name] = {
                "status": status.status,
                "attempts": status.attempts,
                "last_error": status.error_message,
            }

    stages = []
    for stage in protocol_stack:
        name = stage.get("name", "unknown")
        status_info = stage_statuses.get(name, {})
        stages.append(
            StageInfo(
                name=name,
                role=stage.get("role", "unknown"),
                status=status_info.get("status", "pending"),
                attempts=status_info.get("attempts", 0),
                last_error=status_info.get("last_error"),
            )
        )

    context = _get_session_context(orchestrator, session_id)
    bootstrap_complete = context.bootstrap_complete if context else False

    return StageListResponse(
        session_id=session_id,
        stages=stages,
        bootstrap_complete=bootstrap_complete,
    )


@router.post("/{session_id}/stages/{stage_name}/rerun")
async def rerun_stage(
    session_id: str,
    stage_name: str,
    orchestrator=Depends(get_orchestrator),
):
    """
    Re-run a specific bootstrap stage.

    Useful for refreshing tokens or testing stage execution.
    Only works for bootstrap stages when session is not running.
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    from core.models import FuzzSessionStatus
    if session.status == FuzzSessionStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail="Cannot rerun stage while session is running. Stop the session first.",
        )

    stage_runner = _get_stage_runner(orchestrator, session_id)
    if not stage_runner:
        raise HTTPException(status_code=400, detail="Session has no stage runner")

    try:
        await stage_runner.rerun_stage(stage_name)
        logger.info("stage_rerun_via_api", session_id=session_id, stage_name=stage_name)
        return {"status": "success", "stage": stage_name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("stage_rerun_failed", session_id=session_id, stage_name=stage_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Stage rerun failed: {e}")


# --------------------------------------------------------------------------
# Connection Endpoints
# --------------------------------------------------------------------------


@router.get("/{session_id}/connection", response_model=ConnectionStatusResponse)
async def get_connection_status(session_id: str, orchestrator=Depends(get_orchestrator)):
    """
    Get connection status for a session.

    Returns connection mode and active connection statistics.
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    conn_manager = _get_connection_manager(orchestrator, session_id)
    if not conn_manager:
        return ConnectionStatusResponse(
            session_id=session_id,
            connection_mode="per_test",
            active_connections=[],
        )

    # Get connection mode from session config
    connection_mode = getattr(session, "connection_mode", "per_test")

    # Get active transports
    connections = []
    for conn_id, transport in conn_manager._transports.items():
        if conn_id.startswith(session_id):
            stats = transport.get_stats()
            connections.append(
                ConnectionInfo(
                    connection_id=conn_id,
                    connected=transport.connected,
                    healthy=transport.healthy,
                    bytes_sent=stats.get("bytes_sent", 0),
                    bytes_received=stats.get("bytes_received", 0),
                    send_count=stats.get("send_count", 0),
                    recv_count=stats.get("recv_count", 0),
                    reconnect_count=stats.get("reconnect_count", 0),
                    created_at=stats.get("created_at"),
                    last_send=stats.get("last_send"),
                    last_recv=stats.get("last_recv"),
                )
            )

    return ConnectionStatusResponse(
        session_id=session_id,
        connection_mode=connection_mode,
        active_connections=connections,
    )


@router.post("/{session_id}/connection/reconnect")
async def reconnect(
    session_id: str,
    rebootstrap: bool = False,
    orchestrator=Depends(get_orchestrator),
):
    """
    Trigger reconnection for a session.

    Args:
        rebootstrap: If true, clear context and re-run bootstrap stages
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    conn_manager = _get_connection_manager(orchestrator, session_id)
    if not conn_manager:
        raise HTTPException(status_code=400, detail="Session has no connection manager")

    try:
        bootstrapped = await conn_manager.reconnect(session, rebootstrap=rebootstrap)
        logger.info(
            "connection_reconnect_via_api",
            session_id=session_id,
            rebootstrap=rebootstrap,
            bootstrapped=bootstrapped,
        )
        return {
            "status": "reconnected",
            "rebootstrap": rebootstrap,
            "bootstrapped": bootstrapped,
        }
    except Exception as e:
        logger.error("connection_reconnect_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Reconnect failed: {e}")


# --------------------------------------------------------------------------
# Heartbeat Endpoints
# --------------------------------------------------------------------------


@router.get("/{session_id}/heartbeat", response_model=HeartbeatStatusResponse)
async def get_heartbeat_status(session_id: str, orchestrator=Depends(get_orchestrator)):
    """
    Get heartbeat status for a session.

    Returns whether heartbeat is enabled, its status, and statistics.
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    scheduler = _get_heartbeat_scheduler(orchestrator)
    if not scheduler:
        return HeartbeatStatusResponse(
            session_id=session_id,
            enabled=False,
        )

    status = scheduler.get_status(session_id)
    if not status:
        return HeartbeatStatusResponse(
            session_id=session_id,
            enabled=session.heartbeat_enabled,
        )

    return HeartbeatStatusResponse(
        session_id=session_id,
        enabled=True,
        status=status.get("status"),
        interval_ms=status.get("interval_ms"),
        total_sent=status.get("total_sent", 0),
        failures=status.get("failures", 0),
        last_sent=status.get("last_sent"),
        last_ack=status.get("last_ack"),
    )


@router.post("/{session_id}/heartbeat/reset")
async def reset_heartbeat_failures(session_id: str, orchestrator=Depends(get_orchestrator)):
    """
    Reset heartbeat failure count.

    Use after manual reconnection to clear the failure counter.
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    scheduler = _get_heartbeat_scheduler(orchestrator)
    if not scheduler:
        raise HTTPException(status_code=400, detail="Heartbeat scheduler not available")

    if not scheduler.is_running(session_id):
        raise HTTPException(status_code=400, detail="Heartbeat not running for this session")

    scheduler.reset_failures(session_id)
    logger.info("heartbeat_failures_reset_via_api", session_id=session_id)
    return {"status": "reset", "session_id": session_id}


# --------------------------------------------------------------------------
# Replay Endpoints
# --------------------------------------------------------------------------


@router.post("/{session_id}/replay", response_model=OrchestratedReplayResponse)
async def orchestrated_replay(
    session_id: str,
    request: OrchestratedReplayRequest,
    orchestrator=Depends(get_orchestrator),
    plugin_manager=Depends(get_plugin_manager),
):
    """
    Replay executions with context reconstruction.

    Supports three modes:
    - fresh: Re-run bootstrap stages, re-serialize with new context
    - stored: Replay exact historical bytes, restore context from snapshot
    - skip: No bootstrap, use stored bytes, empty context

    Use for reproducing issues or testing protocol state.
    """
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate mode
    valid_modes = ["fresh", "stored", "skip"]
    if request.mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{request.mode}'. Must be one of: {valid_modes}",
        )

    from core.models import FuzzSessionStatus
    if session.status == FuzzSessionStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail="Cannot replay while session is running. Stop the session first.",
        )

    # Get or create replay executor
    replay_executor = _get_or_create_replay_executor(orchestrator, plugin_manager)

    from core.engine.replay_executor import ReplayMode, ReplayError

    mode_map = {
        "fresh": ReplayMode.FRESH,
        "stored": ReplayMode.STORED,
        "skip": ReplayMode.SKIP,
    }

    try:
        result = await replay_executor.replay_up_to(
            session=session,
            target_sequence=request.target_sequence,
            mode=mode_map[request.mode],
            delay_ms=request.delay_ms,
            stop_on_error=request.stop_on_error,
        )

        return OrchestratedReplayResponse(
            session_id=session_id,
            replayed_count=result.replayed_count,
            skipped_count=result.skipped_count,
            results=[
                OrchestratedReplayResult(
                    original_sequence=r.original_sequence,
                    status=r.status,
                    response_preview=r.response_preview,
                    error=r.error,
                    duration_ms=r.duration_ms,
                    matched_original=r.matched_original,
                )
                for r in result.results
            ],
            context_after=result.context_after,
            warnings=result.warnings,
            duration_ms=result.duration_ms,
        )

    except ReplayError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("replay_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Replay failed: {e}")


# --------------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------------


def _get_session_context(orchestrator, session_id: str):
    """Get the ProtocolContext for a session if it exists."""
    # Context is stored per-session in orchestrator's context registry
    contexts = getattr(orchestrator, "_session_contexts", {})
    return contexts.get(session_id)


def _get_or_create_session_context(orchestrator, session_id: str):
    """Get or create a ProtocolContext for a session."""
    from core.engine.protocol_context import ProtocolContext

    if not hasattr(orchestrator, "_session_contexts"):
        orchestrator._session_contexts = {}

    if session_id not in orchestrator._session_contexts:
        orchestrator._session_contexts[session_id] = ProtocolContext()

    return orchestrator._session_contexts[session_id]


def _get_stage_runner(orchestrator, session_id: str):
    """Get the StageRunner for a session if it exists."""
    stage_runners = getattr(orchestrator, "_stage_runners", {})
    return stage_runners.get(session_id)


def _get_connection_manager(orchestrator, session_id: str):
    """Get the ConnectionManager for a session if it exists."""
    # ConnectionManager is shared, but we check if session has connections
    return getattr(orchestrator, "_connection_manager", None)


def _get_heartbeat_scheduler(orchestrator):
    """Get the HeartbeatScheduler if it exists."""
    return getattr(orchestrator, "_heartbeat_scheduler", None)


def _get_or_create_replay_executor(orchestrator, plugin_manager):
    """Get or create a ReplayExecutor."""
    from core.engine.replay_executor import ReplayExecutor
    from core.engine.connection_manager import ConnectionManager

    if not hasattr(orchestrator, "_replay_executor"):
        # Create connection manager if needed
        if not hasattr(orchestrator, "_connection_manager"):
            orchestrator._connection_manager = ConnectionManager()

        orchestrator._replay_executor = ReplayExecutor(
            plugin_manager=plugin_manager,
            connection_manager=orchestrator._connection_manager,
            history_store=orchestrator.history_store,
            stage_runner=_get_stage_runner(orchestrator, None),  # Optional
        )

    return orchestrator._replay_executor
