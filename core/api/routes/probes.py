"""Probe management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from core.api.deps import get_probe_manager, get_orchestrator
from core.models import ProbeTestResult, ProbeWorkItem, TransportProtocol

router = APIRouter(prefix="/api/probes", tags=["probes"])


@router.post("/register")
async def register_probe(probe_info: dict, probe_manager=Depends(get_probe_manager)):
    required_fields = {"probe_id", "hostname", "target_host", "target_port"}
    missing = [field for field in required_fields if field not in probe_info]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {', '.join(missing)}")

    transport_raw = probe_info.get("transport", TransportProtocol.TCP.value)
    try:
        transport = TransportProtocol(str(transport_raw).lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid transport: {transport_raw}")

    return probe_manager.register_probe(
        probe_id=probe_info["probe_id"],
        hostname=probe_info["hostname"],
        target_host=probe_info["target_host"],
        target_port=int(probe_info["target_port"]),
        transport=transport,
    )


@router.post("/{probe_id}/heartbeat")
async def probe_heartbeat(probe_id: str, status: dict, probe_manager=Depends(get_probe_manager)):
    updated = probe_manager.heartbeat(
        probe_id,
        cpu_usage=status.get("cpu_usage", 0.0),
        memory_usage_mb=status.get("memory_usage_mb", 0.0),
        active_tests=status.get("active_tests", 0),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Probe not registered")
    return {"status": "ok"}


@router.get("/{probe_id}/next-case", response_model=ProbeWorkItem | None)
async def probe_next_case(probe_id: str, probe_manager=Depends(get_probe_manager)):
    work = await probe_manager.request_work(probe_id)
    if not work:
        return JSONResponse(status_code=204, content=None)
    return work


@router.post("/{probe_id}/result")
async def probe_submit_result(
    probe_id: str,
    result: ProbeTestResult,
    probe_manager=Depends(get_probe_manager),
    orchestrator=Depends(get_orchestrator),
):
    response = await orchestrator.handle_probe_result(probe_id, result)
    return response
