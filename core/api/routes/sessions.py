"""Session and execution management endpoints."""
from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException

from core.api.deps import get_orchestrator
from core.models import (
    ExecutionHistoryResponse,
    FuzzConfig,
    FuzzSession,
    ReplayRequest,
    ReplayResponse,
    TestCaseExecutionRecord,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=FuzzSession)
async def create_session(config: FuzzConfig, orchestrator=Depends(get_orchestrator)):
    try:
        session = await orchestrator.create_session(config)
        logger.info("session_created_via_api", session_id=session.id)
        return session
    except Exception as exc:
        logger.error("failed_to_create_session", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("", response_model=List[FuzzSession])
async def list_sessions(orchestrator=Depends(get_orchestrator)):
    return orchestrator.list_sessions()


@router.get("/{session_id}", response_model=FuzzSession)
async def get_session(session_id: str, orchestrator=Depends(get_orchestrator)):
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/{session_id}/start")
async def start_session(session_id: str, orchestrator=Depends(get_orchestrator)):
    success = await orchestrator.start_session(session_id)
    if not success:
        # Try to get the specific error message from the session
        session = orchestrator.get_session(session_id)
        error_detail = session.error_message if session and session.error_message else "Failed to start session"
        raise HTTPException(status_code=400, detail=error_detail)
    return {"status": "started", "session_id": session_id}


@router.post("/{session_id}/stop")
async def stop_session(session_id: str, orchestrator=Depends(get_orchestrator)):
    success = await orchestrator.stop_session(session_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to stop session")
    return {"status": "stopped", "session_id": session_id}


@router.delete("/{session_id}")
async def delete_session(session_id: str, orchestrator=Depends(get_orchestrator)):
    success = await orchestrator.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    logger.info("session_deleted_via_api", session_id=session_id)
    return {"status": "deleted", "session_id": session_id}


@router.get("/{session_id}/stats")
async def get_session_stats(session_id: str, orchestrator=Depends(get_orchestrator)):
    stats = orchestrator.get_session_stats(session_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Session not found")
    return stats


@router.get("/{session_id}/state_coverage")
async def get_session_state_coverage(session_id: str, orchestrator=Depends(get_orchestrator)):
    coverage = orchestrator.get_state_coverage(session_id)
    if coverage:
        return coverage
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    raise HTTPException(status_code=404, detail="Session is not stateful or has no coverage yet")


@router.get("/{session_id}/execution_history", response_model=ExecutionHistoryResponse)
async def get_execution_history(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    since: Optional[str] = None,
    until: Optional[str] = None,
    orchestrator=Depends(get_orchestrator),
):
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    since_dt = datetime.fromisoformat(since) if since else None
    until_dt = datetime.fromisoformat(until) if until else None
    executions = orchestrator.get_execution_history(
        session_id,
        limit=limit,
        offset=offset,
        since=since_dt,
        until=until_dt,
    )
    total_count = orchestrator.history_store.total_count(session_id)
    return ExecutionHistoryResponse(
        session_id=session_id,
        total_count=total_count,
        returned_count=len(executions),
        executions=executions,
    )


@router.get("/{session_id}/execution/at_time", response_model=TestCaseExecutionRecord)
async def get_execution_at_time(session_id: str, timestamp: str, orchestrator=Depends(get_orchestrator)):
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        timestamp_dt = datetime.fromisoformat(timestamp)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format. Use ISO 8601.")

    execution = orchestrator.find_execution_at_time(session_id, timestamp_dt)
    if not execution:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No execution found at {timestamp}. The timestamp may be outside the recorded range, or the execution may have been rotated out of history."
            ),
        )
    return execution


@router.get("/{session_id}/execution/{sequence_number}", response_model=TestCaseExecutionRecord)
async def get_execution_by_sequence(session_id: str, sequence_number: int, orchestrator=Depends(get_orchestrator)):
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    execution = orchestrator.find_execution_by_sequence(session_id, sequence_number)
    if not execution:
        raise HTTPException(
            status_code=404,
            detail="Execution not found. It may have been rotated out of history (keeping last 5000).",
        )
    return execution


@router.post("/{session_id}/execution/replay", response_model=ReplayResponse)
async def replay_executions(session_id: str, request: ReplayRequest, orchestrator=Depends(get_orchestrator)):
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not request.sequence_numbers:
        raise HTTPException(status_code=400, detail="sequence_numbers cannot be empty")
    if len(request.sequence_numbers) > 100:
        raise HTTPException(status_code=400, detail="Cannot replay more than 100 test cases at once")
    if request.delay_ms < 0:
        raise HTTPException(status_code=400, detail="delay_ms cannot be negative")

    results = await orchestrator.replay_executions(
        session_id,
        request.sequence_numbers,
        delay_ms=request.delay_ms,
    )
    return ReplayResponse(replayed_count=len(results), results=results)


@router.get("/{session_id}/state_graph")
async def get_state_graph(session_id: str, orchestrator=Depends(get_orchestrator)):
    """
    Get state graph data for visualization.

    Returns nodes (states) and edges (transitions) with coverage information.
    """
    from core.plugin_loader import plugin_manager

    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Load protocol to get state model
    try:
        protocol = plugin_manager.load_plugin(session.protocol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load protocol: {str(e)}")

    if not protocol.state_model:
        raise HTTPException(
            status_code=404,
            detail="Protocol does not have a state model"
        )

    state_model = protocol.state_model
    state_coverage = session.state_coverage or {}
    transition_coverage = session.transition_coverage or {}

    # Calculate total tests per state and result breakdown
    total_tests = session.total_tests or 0

    # Build nodes (states)
    nodes = []
    for state in state_model.get("states", []):
        visit_count = state_coverage.get(state, 0)

        # Determine node color based on coverage and results
        if visit_count == 0:
            color = "#cccccc"  # Gray - never visited
            group = "unvisited"
        elif state == session.current_state:
            color = "#4CAF50"  # Green - current state
            group = "current"
        elif visit_count > 0:
            # Blue gradient based on visit frequency
            intensity = min(visit_count / max(state_coverage.values()) if state_coverage.values() else 1, 1.0)
            blue_value = int(100 + (155 * intensity))
            color = f"#{blue_value:02x}{blue_value:02x}ff"
            group = "visited"
        else:
            color = "#2196F3"  # Blue - visited
            group = "visited"

        nodes.append({
            "id": state,
            "label": state,
            "title": f"{state}\nVisits: {visit_count}",
            "value": visit_count,  # Size based on visit count
            "color": color,
            "group": group,
            "visits": visit_count
        })

    # Build edges (transitions)
    edges = []
    for idx, transition in enumerate(state_model.get("transitions", [])):
        from_state = transition.get("from")
        to_state = transition.get("to")
        message_type = transition.get("message_type", "")

        transition_key = f"{from_state}->{to_state}"
        usage_count = transition_coverage.get(transition_key, 0)

        # Edge color and width based on usage
        if usage_count == 0:
            color = "#dddddd"
            width = 1
            dashes = True
        else:
            color = "#2196F3"
            # Width based on usage frequency
            max_usage = max(transition_coverage.values()) if transition_coverage.values() else 1
            width = 1 + (5 * (usage_count / max_usage))
            dashes = False

        edges.append({
            "id": f"edge_{idx}",
            "from": from_state,
            "to": to_state,
            "label": message_type,
            "title": f"{from_state} → {to_state}\n{message_type}\nCount: {usage_count}",
            "value": usage_count,
            "color": color,
            "width": width,
            "dashes": dashes,
            "arrows": "to"
        })

    # Calculate graph statistics
    total_states = len(state_model.get("states", []))
    visited_states = sum(1 for count in state_coverage.values() if count > 0)
    coverage_pct = (visited_states / total_states * 100) if total_states > 0 else 0

    total_transitions = len(state_model.get("transitions", []))
    taken_transitions = sum(1 for count in transition_coverage.values() if count > 0)
    transition_coverage_pct = (taken_transitions / total_transitions * 100) if total_transitions > 0 else 0

    return {
        "session_id": session_id,
        "protocol": session.protocol,
        "current_state": session.current_state,
        "nodes": nodes,
        "edges": edges,
        "statistics": {
            "total_states": total_states,
            "visited_states": visited_states,
            "state_coverage_pct": round(coverage_pct, 1),
            "total_transitions": total_transitions,
            "taken_transitions": taken_transitions,
            "transition_coverage_pct": round(transition_coverage_pct, 1),
            "total_tests": total_tests
        }
    }
