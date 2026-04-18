"""Central logging helpers.

Provides structured JSON logging via structlog with dual output to
stdout and rotating log files. All components use the same format
so logs can be aggregated and searched consistently.

Configuration:
    FUZZER_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR  (default: INFO)
    FUZZER_LOG_DIR=/path/to/logs               (default: <project>/logs)

Log files:
    logs/core-api.log   — Core API + engine events
    logs/probe.log      — Probe events (when running)
    logs/target-mgr.log — Target Manager events
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog
import structlog.stdlib

from core.config import settings


def _resolve_level(level_str: str) -> int:
    """Convert a level name to a logging int, default to INFO."""
    return getattr(logging, level_str.upper(), logging.INFO)


def _build_file_handler(component: str, level: int) -> RotatingFileHandler:
    log_dir: Path = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{component}.log"
    handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5)
    handler.setLevel(level)
    # Use structlog's ProcessorFormatter so file output is clean JSON
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=False),
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
        ],
    ))
    return handler


def _build_console_handler(level: int) -> logging.StreamHandler:
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=True),
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
        ],
    ))
    return handler


def setup_logging(component: str = "core", level: int | None = None) -> None:
    """Configure structlog + stdlib logging for a component.

    Args:
        component: Name used for the log file (e.g. 'core-api', 'probe').
        level: Override log level. If None, reads FUZZER_LOG_LEVEL env var.
    """
    if level is None:
        level = _resolve_level(settings.log_level)

    # Reset root logger handlers to avoid duplicate output on re-init
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(_build_console_handler(level))
    root.addHandler(_build_file_handler(component, level))

    # Quiet noisy third-party loggers
    for noisy in ("uvicorn.access", "uvicorn.error", "httpcore", "httpx"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    structlog.get_logger().info(
        "logging_initialized",
        component=component,
        level=logging.getLevelName(level),
        log_file=str(settings.log_dir / f"{component}.log"),
    )
