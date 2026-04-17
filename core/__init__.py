"""
Portable Proprietary Protocol Fuzzer - Core Module
"""
from datetime import datetime, timezone

__version__ = "0.1.0"


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime.

    Replaces the deprecated ``datetime.utcnow()`` while keeping the
    return type consistent with the rest of the codebase (naive UTC).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
