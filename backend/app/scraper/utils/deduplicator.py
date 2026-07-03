"""
app/scraper/utils/deduplicator.py

Fingerprint-based deduplication.

Design decisions:
- SHA256 fingerprint from title+company+location (same job on 2 sites = same hash)
- bulk_check() loads all existing hashes into a set at pipeline start —
  avoids one DB query per job (500 jobs = 1 query instead of 500)
- is_duplicate() kept for single-job lookups (used in orchestrator updates)
"""
import hashlib
import logging

from app.models.internship import Internship

logger = logging.getLogger(__name__)


class Deduplicator:

    def generate_hash(self, title: str, company: str, location: str) -> str:
        """
        Create a stable fingerprint for a job posting.
        Same job posted on multiple sites → same hash → one DB row.

        Uses SHA256 (overkill for dedup but collision-safe and already in stdlib).
        """
        normalized = (
            f"{title.strip().lower()}"
            f"|{company.strip().lower()}"
            f"|{location.strip().lower()}"
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def is_duplicate(self, hash_value: str, db) -> Internship | None:
        """
        Single-job duplicate check. Returns existing Internship or None.
        Used during update path in orchestrator.

        SA 1.x compatible: uses .query() not select().scalar_one_or_none()
        """
        return (
            db.query(Internship)
            .filter(Internship.duplicate_hash == hash_value)
            .first()
        )

    def bulk_load_existing_hashes(self, db) -> set[str]:
        """
        Load ALL existing fingerprints from DB into a Python set.

        WHY: Without this, processing 500 jobs = 500 individual DB queries
        to check "does this hash exist?". With this, we do 1 query at
        pipeline start and check membership in O(1) against the in-memory set.

        Called once per pipeline run, before processing any jobs.
        Returns a set of hash strings.
        """
        rows = db.query(Internship.duplicate_hash).filter(
            Internship.duplicate_hash.isnot(None)
        ).all()
        hashes = {row[0] for row in rows if row[0]}
        logger.info("deduplicator.loaded_hashes count=%d", len(hashes))
        return hashes