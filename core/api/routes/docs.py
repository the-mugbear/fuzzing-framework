"""API routes for serving documentation files."""
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/docs", tags=["docs"])

# Base path for documentation files
# In container: /app, in development: project root
_file_path = Path(__file__).resolve()
# Navigate up: routes -> api -> core -> project_root
DOCS_BASE = _file_path.parent.parent.parent.parent
# Override for container environment
if os.environ.get("FUZZER_CORPUS_DIR", "").startswith("/app"):
    DOCS_BASE = Path("/app")


class DocResponse(BaseModel):
    """Response containing markdown content."""
    path: str
    content: str
    title: Optional[str] = None


class DocListItem(BaseModel):
    """A single documentation file entry."""
    path: str
    title: str
    description: Optional[str] = None


class DocListResponse(BaseModel):
    """List of available documentation files."""
    docs: list[DocListItem]


# Allowed documentation paths (security: prevent path traversal)
ALLOWED_PATHS = {
    "CHANGELOG.md",
    "docs/README.md",
    "docs/QUICKSTART.md",
    "docs/USER_GUIDE.md",
    "docs/PROTOCOL_PLUGIN_GUIDE.md",
    "docs/MUTATION_STRATEGIES.md",
    "docs/STATE_COVERAGE_GUIDE.md",
    "docs/TEMPLATE_QUICK_REFERENCE.md",
    "docs/PROTOCOL_SERVER_TEMPLATES.md",
    "docs/ORCHESTRATED_SESSIONS_GUIDE.md",
    "docs/developer/01_architectural_overview.md",
    "docs/developer/02_mutation_engine.md",
    "docs/developer/03_stateful_fuzzing.md",
    "docs/developer/04_data_management.md",
    "docs/developer/05_agent_and_core_communication.md",
    "docs/developer/06_first_debug_session.md",
    "docs/developer/ORCHESTRATED_SESSIONS_ARCHITECTURE.md",
}


def extract_title(content: str) -> Optional[str]:
    """Extract the first H1 heading from markdown content."""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


@router.get("", response_model=DocListResponse)
async def list_docs():
    """List all available documentation files."""
    docs = []
    for path in sorted(ALLOWED_PATHS):
        full_path = DOCS_BASE / path
        if full_path.exists():
            try:
                content = full_path.read_text(encoding="utf-8")
                title = extract_title(content) or path.split("/")[-1].replace(".md", "")
                docs.append(DocListItem(path=path, title=title))
            except Exception:
                docs.append(DocListItem(path=path, title=path.split("/")[-1]))
    return DocListResponse(docs=docs)


@router.get("/{path:path}", response_model=DocResponse)
async def get_doc(path: str):
    """
    Get the content of a documentation file.

    Args:
        path: Relative path to the doc file (e.g., "docs/QUICKSTART.md")

    Returns:
        DocResponse with the markdown content
    """
    # Security: only allow whitelisted paths
    if path not in ALLOWED_PATHS:
        raise HTTPException(status_code=404, detail=f"Documentation not found: {path}")

    full_path = DOCS_BASE / path

    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"Documentation file not found: {path}")

    try:
        content = full_path.read_text(encoding="utf-8")
        title = extract_title(content)
        return DocResponse(path=path, content=content, title=title)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read documentation: {str(e)}")
