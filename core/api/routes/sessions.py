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
