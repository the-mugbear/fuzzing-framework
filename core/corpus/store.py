"""
Corpus management and storage
"""
import hashlib
import json
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

        # In-memory cache
        self._seed_cache: Dict[str, bytes] = {}
        self._load_seeds()

    def _load_seeds(self):
        """Load all seeds from disk into memory"""
        for seed_file in self.seeds_dir.glob("*.bin"):
            try:
                seed_id = seed_file.stem
                with open(seed_file, "rb") as f:
                    self._seed_cache[seed_id] = f.read()
                logger.debug("loaded_seed", seed_id=seed_id)
            except Exception as e:
                logger.error("failed_to_load_seed", seed_file=str(seed_file), error=str(e))

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
        """Retrieve a seed by ID"""
        return self._seed_cache.get(seed_id)

    def get_all_seeds(self) -> List[bytes]:
        """Get all seeds as a list"""
        return list(self._seed_cache.values())

    def get_seed_ids(self) -> List[str]:
        """Get all seed IDs"""
        return list(self._seed_cache.keys())

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
