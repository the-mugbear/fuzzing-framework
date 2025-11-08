"""Central logging helpers"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import structlog
import structlog.stdlib

from core.config import settings

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def _build_file_handler(component: str) -> RotatingFileHandler:
    log_dir: Path = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{component}.log"
    handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5)
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
    return handler


def setup_logging(component: str = "core", level: int = logging.INFO) -> None:
    """Configure structlog + stdlib logging for a component"""
    handlers = [logging.StreamHandler(), _build_file_handler(component)]

    logging.basicConfig(level=level, handlers=handlers, format=_DEFAULT_FORMAT)

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.getLogger(__name__).info("logging_initialized", extra={"component": component})
