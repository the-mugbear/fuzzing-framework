"""Agent management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from core.api.deps import get_agent_manager, get_orchestrator
from core.models import AgentTestResult, AgentWorkItem

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("/register")
async def register_agent(agent_info: dict, agent_manager=Depends(get_agent_manager)):
    required_fields = {"agent_id", "hostname", "target_host", "target_port"}
    missing = [field for field in required_fields if field not in agent_info]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {', '.join(missing)}")

    return agent_manager.register_agent(
        agent_id=agent_info["agent_id"],
        hostname=agent_info["hostname"],
        target_host=agent_info["target_host"],
        target_port=int(agent_info["target_port"]),
    )


@router.post("/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: str, status: dict, agent_manager=Depends(get_agent_manager)):
    updated = agent_manager.heartbeat(
        agent_id,
        cpu_usage=status.get("cpu_usage", 0.0),
        memory_usage_mb=status.get("memory_usage_mb", 0.0),
        active_tests=status.get("active_tests", 0),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not registered")
    return {"status": "ok"}


@router.get("/{agent_id}/next-case", response_model=AgentWorkItem | None)
async def agent_next_case(agent_id: str, agent_manager=Depends(get_agent_manager)):
    work = await agent_manager.request_work(agent_id)
    if not work:
        return JSONResponse(status_code=204, content=None)
    return work


@router.post("/{agent_id}/result")
async def agent_submit_result(
    agent_id: str,
    result: AgentTestResult,
    agent_manager=Depends(get_agent_manager),
    orchestrator=Depends(get_orchestrator),
):
    response = await orchestrator.handle_agent_result(agent_id, result)
    return response
