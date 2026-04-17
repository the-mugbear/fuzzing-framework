"""Registry — discovers test server scripts and extracts metadata."""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Dict, Optional

from target_manager.models import ServerMeta, TransportType

logger = logging.getLogger("target_manager.registry")

# Fallback metadata for servers that don't (yet) have __server_meta__
_BUILTIN_FALLBACKS: Dict[str, dict] = {
    "simple_tcp_server.py": {
        "name": "Simple TCP Echo",
        "description": "Generic TCP echo server — reflects raw bytes for payload inspection",
        "transport": "tcp",
        "default_port": 9999,
        "compatible_plugins": ["minimal_tcp"],
        "vulnerabilities": 3,
    },
    "feature_reference_server.py": {
        "name": "Feature Reference",
        "description": "Full protocol server with 10 intentional vulnerabilities (★ to ★★★★★)",
        "transport": "tcp",
        "default_port": 9999,
        "compatible_plugins": ["feature_reference"],
        "vulnerabilities": 10,
    },
    "feature_showcase_server.py": {
        "name": "Feature Showcase",
        "description": "Interactive server for the feature_showcase protocol with 5 intentional vulns",
        "transport": "tcp",
        "default_port": 9001,
        "compatible_plugins": ["feature_showcase"],
        "vulnerabilities": 5,
    },
    "udp_server.py": {
        "name": "Simple UDP",
        "description": "UDP echo server with command byte flip for the minimal_udp plugin",
        "transport": "udp",
        "default_port": 9999,
        "compatible_plugins": ["minimal_udp"],
        "vulnerabilities": 0,
    },
    "template_tcp_server.py": {
        "name": "TCP Template",
        "description": "Skeleton TCP server — copy and customize for your protocol",
        "transport": "tcp",
        "default_port": 9999,
        "compatible_plugins": [],
        "vulnerabilities": 0,
    },
    "template_udp_server.py": {
        "name": "UDP Template",
        "description": "Skeleton UDP server — copy and customize for your protocol",
        "transport": "udp",
        "default_port": 9999,
        "compatible_plugins": [],
        "vulnerabilities": 0,
    },
}


def _extract_meta_from_source(source: str) -> Optional[dict]:
    """Try to extract __server_meta__ dict from Python source using AST."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__server_meta__":
                    try:
                        return ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        return None
    return None


def discover_servers(tests_dir: Path) -> Dict[str, ServerMeta]:
    """Scan tests/ for server scripts and build a catalog.

    Priority:
    1. __server_meta__ dict defined in the script (AST-extracted)
    2. Built-in fallback metadata (for known scripts)
    3. Skip if neither available
    """
    catalog: Dict[str, ServerMeta] = {}

    if not tests_dir.is_dir():
        logger.warning("tests_dir_not_found", extra={"path": str(tests_dir)})
        return catalog

    for py_file in sorted(tests_dir.glob("*_server.py")):
        filename = py_file.name
        source = py_file.read_text(encoding="utf-8", errors="replace")

        # Try AST extraction first
        meta_dict = _extract_meta_from_source(source)
        if meta_dict:
            meta_dict.setdefault("script", filename)
            try:
                catalog[filename] = ServerMeta(**meta_dict)
                logger.info("discovered_server_meta", extra={"script": filename, "source": "ast"})
                continue
            except Exception as exc:
                logger.warning(
                    "invalid_server_meta",
                    extra={"script": filename, "error": str(exc)},
                )

        # Fall back to built-in metadata
        if filename in _BUILTIN_FALLBACKS:
            fb = {**_BUILTIN_FALLBACKS[filename], "script": filename}
            catalog[filename] = ServerMeta(**fb)
            logger.info("discovered_server_meta", extra={"script": filename, "source": "builtin"})
        else:
            logger.debug("skipping_unknown_server", extra={"script": filename})

    return catalog
