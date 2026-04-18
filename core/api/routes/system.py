"""System-level endpoints — health, config, logs, diagnostics."""
import io
import platform
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, StreamingResponse

from core.api.deps import get_corpus_store, get_orchestrator
from core.config import settings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
async def system_health(orchestrator=Depends(get_orchestrator), corpus_store=Depends(get_corpus_store)):
    return {
        "status": "healthy",
        "active_sessions": len(orchestrator.active_tasks),
        "total_sessions": len(orchestrator.sessions),
        "corpus_seeds": len(corpus_store.get_seed_ids()),
    }


@router.get("/config")
async def get_config():
    return {
        "plugins_dir": str(settings.plugins_dir),
        "max_concurrent_tests": settings.max_concurrent_tests,
        "mutation_timeout_sec": settings.mutation_timeout_sec,
        "log_level": settings.log_level,
        "log_dir": str(settings.log_dir),
    }


# ─── Log viewing / export endpoints ───


@router.get("/logs")
async def list_log_files():
    """List available log files with sizes."""
    log_dir: Path = settings.log_dir
    if not log_dir.exists():
        return {"files": []}

    files = []
    for f in sorted(log_dir.iterdir()):
        if f.is_file() and f.suffix == ".log":
            stat = f.stat()
            files.append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
    return {"files": files}


@router.get("/logs/{filename}")
async def get_log_file(
    filename: str,
    tail: Optional[int] = Query(None, ge=1, le=50000, description="Return last N lines"),
    level: Optional[str] = Query(None, description="Filter to log level (INFO, WARNING, ERROR)"),
):
    """Read a log file. Use ?tail=N for last N lines, ?level=ERROR for filtering."""
    # Sanitize filename to prevent path traversal
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        return PlainTextResponse("Invalid filename", status_code=400)

    log_path = settings.log_dir / safe_name
    if not log_path.exists() or not log_path.is_file():
        return PlainTextResponse("Log file not found", status_code=404)

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.error("log_read_failed", filename=safe_name, error=str(exc))
        return PlainTextResponse(f"Failed to read log: {exc}", status_code=500)

    lines = text.splitlines()

    # Filter by level if requested
    if level:
        level_upper = level.upper()
        lines = [ln for ln in lines if level_upper in ln]

    # Tail
    if tail and tail < len(lines):
        lines = lines[-tail:]

    return PlainTextResponse(
        "\n".join(lines),
        headers={"X-Log-Total-Lines": str(len(lines))},
    )


@router.get("/logs/{filename}/download")
async def download_log_file(filename: str):
    """Download a raw log file."""
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        return PlainTextResponse("Invalid filename", status_code=400)

    log_path = settings.log_dir / safe_name
    if not log_path.exists() or not log_path.is_file():
        return PlainTextResponse("Log file not found", status_code=404)

    return StreamingResponse(
        open(log_path, "rb"),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# ─── Diagnostic bundle ───


@router.get("/diagnostic-bundle")
async def download_diagnostic_bundle(
    orchestrator=Depends(get_orchestrator),
    corpus_store=Depends(get_corpus_store),
):
    """Generate a ZIP bundle containing logs, session summaries, and system info.

    Users can download this and share it with developers for debugging.
    No sensitive data (credentials, raw payloads) is included.
    """
    logger.info("diagnostic_bundle_requested")
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. System info
        now = datetime.now(timezone.utc)
        sys_info = [
            f"Generated: {now.isoformat()}",
            f"Platform: {platform.platform()}",
            f"Python: {platform.python_version()}",
            f"Log Level: {settings.log_level}",
            f"Max Concurrent Tests: {settings.max_concurrent_tests}",
            f"Mutation Mode: {settings.mutation_mode}",
            f"Corpus Dir: {settings.corpus_dir}",
            f"Log Dir: {settings.log_dir}",
        ]
        zf.writestr("system_info.txt", "\n".join(sys_info))

        # 2. Session summaries (no raw data, just metadata)
        session_lines = []
        for sid, session in orchestrator.sessions.items():
            session_lines.append(
                f"ID: {sid}\n"
                f"  Protocol: {session.protocol}\n"
                f"  Status: {session.status}\n"
                f"  Target: {session.target_host}:{session.target_port}\n"
                f"  Tests: {session.total_tests} | Crashes: {session.crashes} "
                f"| Hangs: {session.hangs} | Anomalies: {session.anomalies}\n"
                f"  Error: {session.error_message or 'none'}\n"
            )
        zf.writestr("sessions.txt", "\n".join(session_lines) if session_lines else "(no sessions)")

        # 3. Corpus stats
        try:
            stats = corpus_store.get_corpus_stats()
            zf.writestr("corpus_stats.txt", "\n".join(f"{k}: {v}" for k, v in stats.items()))
        except Exception as exc:
            zf.writestr("corpus_stats.txt", f"Error getting stats: {exc}")

        # 4. Log files (all .log files, including rotated backups)
        log_dir: Path = settings.log_dir
        if log_dir.exists():
            for f in sorted(log_dir.iterdir()):
                if f.is_file() and (".log" in f.name):
                    try:
                        zf.write(f, f"logs/{f.name}")
                    except OSError:
                        zf.writestr(f"logs/{f.name}.error", "Could not read file")

    buf.seek(0)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    logger.info("diagnostic_bundle_generated", size_bytes=buf.getbuffer().nbytes)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="fuzzer-diagnostic-{timestamp}.zip"'},
    )
