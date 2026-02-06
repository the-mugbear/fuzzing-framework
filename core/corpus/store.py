"""
Corpus Store - Manages seed corpus and crash findings persistence.

This module provides the storage layer for fuzzing inputs (seeds) and
discovered findings (crashes, hangs, anomalies).

Component Overview:
-------------------
The CorpusStore manages two types of data:
1. Seeds: Input data used as mutation base
2. Findings: Crash reports and reproducers

Key Responsibilities:
--------------------
1. Seed Management:
   - Add seeds with automatic deduplication (SHA-256)
   - LRU cache for efficient memory usage
   - On-demand loading from disk
   - Metadata tracking per seed

2. Finding Storage:
   - Save crash reports with reproducers
   - Multiple formats (JSON for humans, MessagePack for efficiency)
   - Per-session finding organization
   - Finding enumeration and retrieval

3. Memory Efficiency:
   - LRU cache prevents unbounded memory growth
   - Configurable cache size via settings
   - Lazy loading of seed content

Storage Layout:
--------------
    corpus/
    ├── seeds/
    │   ├── <sha256>.bin      # Raw seed data
    │   └── <sha256>.meta     # Seed metadata (JSON)
    └── findings/
        └── <finding_id>/
            ├── input.bin     # Reproducer data
            ├── report.json   # Human-readable report
            └── report.msgpack # Binary report

LRU Cache Behavior:
------------------
Seeds are cached with LRU (Least Recently Used) eviction:
- Cache hit: seed moved to end (most recently used)
- Cache miss: seed loaded from disk, added to cache
- Cache full: oldest entry evicted before adding new

Usage Example:
-------------
    store = CorpusStore()

    # Add seed (returns existing ID if duplicate)
    seed_id = store.add_seed(b"test data", metadata={"source": "manual"})

    # Get seed (loads from disk if not cached)
    seed_data = store.get_seed(seed_id)

    # Save finding
    finding_id = store.save_finding(session_id, crash_report)

    # List findings
    findings = store.list_findings(session_id)

Configuration:
-------------
- corpus_dir: Root directory for storage (from settings)
- seed_cache_max_size: Maximum LRU cache entries (from settings)

See Also:
--------
- core/engine/crash_handler.py - Creates CrashReport objects
- core/models.py - CrashReport, TestCase definitions
- docs/developer/04_data_management.md - Data flow documentation
"""
import hashlib
import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import msgpack
import structlog

from core.config import settings
from core.models import CrashReport, TestCase

logger = structlog.get_logger()


class CorpusStore:
    """
    Manages seed corpus and interesting test cases

    Stores seeds and mutations that discover new behavior,
    with deduplication and metadata tracking.
    """

    def __init__(self, corpus_dir: Optional[Path] = None):
        self.corpus_dir = corpus_dir or settings.corpus_dir
        self.corpus_dir.mkdir(parents=True, exist_ok=True)
        self.seeds_dir = self.corpus_dir / "seeds"
        self.findings_dir = self.corpus_dir / "findings"
        self.seeds_dir.mkdir(exist_ok=True)
        self.findings_dir.mkdir(exist_ok=True)

        # LRU cache with maximum size (prevents unbounded memory growth)
        self._seed_cache: OrderedDict[str, bytes] = OrderedDict()
        self._max_cache_size = settings.seed_cache_max_size
        self._load_seed_index()

    def _load_seed_index(self):
        """
        Index available seeds without loading into memory.

        Seeds are loaded on-demand with LRU eviction to prevent
        unbounded memory growth on large corpora.
        """
        seed_count = sum(1 for _ in self.seeds_dir.glob("*.bin"))
        logger.info(
            "corpus_initialized",
            seeds_dir=str(self.seeds_dir),
            seed_count=seed_count,
            max_cache_size=self._max_cache_size
        )

    def _load_seed_from_disk(self, seed_id: str) -> Optional[bytes]:
        """Load a single seed from disk."""
        seed_file = self.seeds_dir / f"{seed_id}.bin"
        if not seed_file.exists():
            return None

        try:
            with open(seed_file, "rb") as f:
                return f.read()
        except Exception as e:
            logger.error("failed_to_load_seed", seed_id=seed_id, error=str(e))
            return None

    def _evict_if_needed(self):
        """Evict least recently used seed from cache if at capacity.

        Uses OrderedDict with move_to_end() in get_seed() to implement LRU.
        Evicts from the front (oldest/least recently used items).
        """
        while len(self._seed_cache) >= self._max_cache_size:
            evicted_id, _ = self._seed_cache.popitem(last=False)  # LRU eviction (oldest first)
            logger.debug("evicted_seed_from_cache", seed_id=evicted_id)

    def add_seed(self, data: bytes, metadata: Optional[Dict] = None) -> str:
        """
        Add a new seed to the corpus

        Args:
            data: Seed data
            metadata: Optional metadata (source, description, etc.)

        Returns:
            Seed ID (SHA256 hash)
        """
        seed_id = hashlib.sha256(data).hexdigest()

        if seed_id in self._seed_cache:
            logger.debug("seed_already_exists", seed_id=seed_id)
            return seed_id

        # Write seed file
        seed_file = self.seeds_dir / f"{seed_id}.bin"
        with open(seed_file, "wb") as f:
            f.write(data)

        # Write metadata
        if metadata:
            meta_file = self.seeds_dir / f"{seed_id}.meta.json"
            with open(meta_file, "w") as f:
                json.dump(metadata, f, indent=2)

        self._seed_cache[seed_id] = data
        logger.info("seed_added", seed_id=seed_id, size=len(data))
        return seed_id

    def get_seed(self, seed_id: str) -> Optional[bytes]:
        """
        Retrieve a seed by ID with LRU caching.

        Seeds are loaded on-demand and cached. Cache uses LRU eviction
        when it reaches max size to prevent unbounded memory growth.
        """
        # Check if in cache
        if seed_id in self._seed_cache:
            # Move to end (mark as recently used)
            self._seed_cache.move_to_end(seed_id)
            return self._seed_cache[seed_id]

        # Not in cache - load from disk
        seed_data = self._load_seed_from_disk(seed_id)
        if seed_data is None:
            return None

        # Add to cache with eviction if needed
        self._evict_if_needed()
        self._seed_cache[seed_id] = seed_data

        return seed_data

    def get_cached_seeds(self) -> List[bytes]:
        """Get all seeds currently in memory cache.

        Note: This only returns cached seeds, not all seeds on disk.
        For comprehensive seed listing, use get_all_seed_ids() and load individually.
        """
        return list(self._seed_cache.values())

    # Backward compatibility alias
    get_all_seeds = get_cached_seeds

    def get_seed_ids(self) -> List[str]:
        """Get IDs of all seeds currently in memory cache.

        Note: This only returns cached seed IDs, not all seeds on disk.
        For comprehensive listing, use get_all_seed_ids().
        """
        return list(self._seed_cache.keys())

    def get_all_seed_ids(self) -> List[str]:
        """Get IDs of all seeds on disk.

        Scans the seeds directory and returns all seed IDs,
        regardless of whether they are currently cached.
        """
        return [f.stem for f in self.seeds_dir.glob("*.bin")]

    def save_finding(self, crash_report: CrashReport, test_case_data: bytes) -> str:
        """
        Save a crash/finding with full reproducer information

        Args:
            crash_report: Crash report metadata
            test_case_data: The input that triggered the crash

        Returns:
            Finding ID
        """
        finding_id = crash_report.id
        finding_dir = self.findings_dir / finding_id
        finding_dir.mkdir(exist_ok=True)

        # Save test case data
        with open(finding_dir / "input.bin", "wb") as f:
            f.write(test_case_data)

        # Save response if available
        if crash_report.response_data:
            with open(finding_dir / "response.bin", "wb") as f:
                f.write(crash_report.response_data)

        # Save crash report as JSON
        with open(finding_dir / "report.json", "w") as f:
            f.write(crash_report.model_dump_json(indent=2))

        # Save as msgpack for efficient storage
        with open(finding_dir / "report.msgpack", "wb") as f:
            # Use model_dump() without mode to get Python objects, and provide
            # a default function to handle datetime serialization
            def msgpack_default(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                return obj
            msgpack.dump(crash_report.model_dump(), f, default=msgpack_default, use_bin_type=True)

        logger.info(
            "finding_saved",
            finding_id=finding_id,
            result_type=crash_report.result_type,
            session_id=crash_report.session_id,
        )
        return finding_id

    def load_finding(self, finding_id: str) -> Optional[tuple[CrashReport, bytes]]:
        """Load a finding by ID"""
        finding_dir = self.findings_dir / finding_id
        if not finding_dir.exists():
            return None

        try:
            # Load report
            with open(finding_dir / "report.json", "r") as f:
                report_data = json.load(f)
                crash_report = CrashReport(**report_data)

            # Load test case
            with open(finding_dir / "input.bin", "rb") as f:
                test_case_data = f.read()

            return crash_report, test_case_data
        except Exception as e:
            logger.error("failed_to_load_finding", finding_id=finding_id, error=str(e))
            return None

    def list_findings(self, session_id: Optional[str] = None) -> List[str]:
        """List all finding IDs, optionally filtered by session"""
        findings = []
        for finding_dir in self.findings_dir.iterdir():
            if not finding_dir.is_dir():
                continue

            if session_id:
                # Check if this finding belongs to the session
                report_file = finding_dir / "report.json"
                if report_file.exists():
                    try:
                        with open(report_file, "r") as f:
                            report_data = json.load(f)
                            if report_data.get("session_id") == session_id:
                                findings.append(finding_dir.name)
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(
                            "corrupted_finding_report",
                            finding_id=finding_dir.name,
                            error=str(e)
                        )
                        # Skip corrupted findings
                        continue
            else:
                findings.append(finding_dir.name)

        return findings

    def get_corpus_stats(self) -> Dict:
        """Get corpus statistics"""
        return {
            "total_seeds": len(self._seed_cache),
            "total_findings": len(list(self.findings_dir.iterdir())),
            "corpus_size_bytes": sum(len(data) for data in self._seed_cache.values()),
            "last_updated": datetime.utcnow().isoformat(),
        }
