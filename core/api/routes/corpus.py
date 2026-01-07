"""Corpus and findings endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from core.api.deps import get_corpus_store

router = APIRouter(prefix="/api/corpus", tags=["corpus"])


@router.get("/seeds")
async def list_seeds(corpus_store=Depends(get_corpus_store)):
    return {"seed_ids": corpus_store.get_seed_ids()}


@router.post("/seeds")
async def upload_seed(
    file: UploadFile = File(...),
    metadata: Optional[str] = None,
    corpus_store=Depends(get_corpus_store),
):
    try:
        data = await file.read()
        import json

        meta = json.loads(metadata) if metadata else {}
        meta["filename"] = file.filename
        seed_id = corpus_store.add_seed(data, metadata=meta)
        return {"seed_id": seed_id, "size": len(data)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stats")
async def get_corpus_stats(corpus_store=Depends(get_corpus_store)):
    return corpus_store.get_corpus_stats()


@router.get("/findings")
async def list_findings(session_id: Optional[str] = None, corpus_store=Depends(get_corpus_store)):
    findings = corpus_store.list_findings(session_id)
    return {"findings": findings, "count": len(findings)}


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: str, include_data: bool = False, corpus_store=Depends(get_corpus_store)):
    result = corpus_store.load_finding(finding_id)
    if not result:
        raise HTTPException(status_code=404, detail="Finding not found")
    crash_report, test_case_data = result

    response = {
        "report": crash_report,
        "reproducer_size": len(test_case_data),
        "reproducer_sha256": crash_report.id,
    }

    # Optionally include the raw binary data as hex for visualization
    if include_data:
        response["reproducer_hex"] = test_case_data.hex()

    return response
