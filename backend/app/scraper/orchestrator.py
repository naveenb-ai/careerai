"""
app/scraper/orchestrator.py

Clean pipeline orchestrator.

Flow:
  SCRAPE → CLEAN → EXTRACT SKILLS → FINGERPRINT → STORE → (embed separately)

Key fixes from old version:
1. Embedding is REMOVED — runs separately via embedding_pipeline.py
2. Recommendation refresh is REMOVED — triggered by API, not scraper
3. DB writes are NOT in the thread pool — scrapers run parallel, writes are serial
4. bulk_load_existing_hashes() replaces per-job DB lookups
5. Each source failure is isolated — doesn't stop other sources
6. LinkedIn removed — blocks scrapers and has legal risk
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

from app.database import SessionLocal
from app.models.internship import Internship
from app.models.internship_skill import InternshipSkill
from app.scraper.sources.internshala import IntershalaScraper
from app.scraper.sources.unstop import UnstopScraper
from app.scraper.sources.shine import ShineScraper
from app.scraper.utils.cleaner import JobCleaner
from app.scraper.utils.deduplicator import Deduplicator
from app.scraper.utils.extractor import SkillExtractor

logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    """
    Coordinates scraping from all sources through the full pipeline.

    Usage:
        orchestrator = ScraperOrchestrator()
        results = orchestrator.scrape_all()
        # {"inserted": 45, "updated": 12, "skipped": 8, "failed": 2, "sources": {...}}
    """

    # Max parallel scraper threads
    # Keep at 3 — more than this risks getting IP-blocked by sites
    MAX_WORKERS = 3

    def __init__(self, groq_api_key: Optional[str] = None) -> None:
        self.cleaner     = JobCleaner()
        self.deduplicator = Deduplicator()
        self.extractor   = SkillExtractor(groq_api_key=groq_api_key)

    def _get_sources(self) -> list:
        """
        Active scraper sources.
        LinkedIn intentionally excluded — blocks scrapers, legal risk.
        Add new sources here as they're implemented.
        """
        return [
            IntershalaScraper(),
            UnstopScraper(),
            ShineScraper(),
        ]

    def scrape_all(self) -> dict:
        """
        Run full pipeline:
        1. Scrape all sources in parallel
        2. Clean all listings
        3. Load existing hashes (1 DB query)
        4. Extract skills + write to DB (serial, safe)
        5. Return summary stats

        Embedding is NOT done here — call embedding_pipeline.run() separately.
        """
        results = {
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "sources": {},
        }

        # ── Phase 1: Scrape all sources in parallel ──────────────────────
        raw_by_source = self._scrape_parallel(results)

        # ── Phase 2: Clean all listings ───────────────────────────────────
        # Done outside DB session — pure CPU work
        cleaned_by_source: dict[str, list[dict]] = {}
        total_raw = sum(len(v) for v in raw_by_source.values())
        total_clean = 0

        for source, raw_listings in raw_by_source.items():
            cleaned = self.cleaner.clean_batch(raw_listings)
            cleaned_by_source[source] = cleaned
            total_clean += len(cleaned)

        logger.info(
            "orchestrator.cleaning_complete raw=%d clean=%d dropped=%d",
            total_raw, total_clean, total_raw - total_clean,
        )

        # ── Phase 3: DB writes (serial — one session, thread-safe) ───────
        db = SessionLocal()
        try:
            # Load all existing hashes in ONE query
            existing_hashes = self.deduplicator.bulk_load_existing_hashes(db)

            for source, listings in cleaned_by_source.items():
                source_stats = {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0}

                for listing in listings:
                    try:
                        status = self._process_one(listing, db, existing_hashes)
                        source_stats[status] += 1
                        results[status] += 1
                    except Exception as exc:
                        # CRITICAL: roll back failed transaction so session
                        # is clean for the next job. Without this, one failure
                        # puts SQLAlchemy into PendingRollbackError state and
                        # ALL subsequent jobs fail with the same error.
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        logger.error(
                            "orchestrator.process_failed source=%s title=%s error=%s detail=%s",
                            source,
                            listing.get("title", "")[:50],
                            type(exc).__name__,
                            str(exc)[:200],   # show actual error message
                        )
                        source_stats["failed"] += 1
                        results["failed"] += 1

                results["sources"][source] = source_stats
                logger.info(
                    "orchestrator.source_complete source=%s stats=%s",
                    source, source_stats,
                )

        finally:
            db.close()

        logger.info("orchestrator.pipeline_complete results=%s", results)
        return results

    def _scrape_parallel(self, results: dict) -> dict[str, list[dict]]:
        """
        Run all scrapers in parallel threads.
        Returns raw listings per source.
        DB is NOT touched here — scrapers only fetch and parse HTML.
        """
        sources = self._get_sources()
        raw_by_source: dict[str, list[dict]] = {}

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_map = {
                executor.submit(self._safe_scrape, scraper): scraper
                for scraper in sources
            }
            for future in as_completed(future_map):
                scraper = future_map[future]
                try:
                    listings = future.result() or []
                except Exception as exc:
                    logger.error(
                        "orchestrator.scraper_crashed source=%s error=%s",
                        scraper.source_name, type(exc).__name__,
                    )
                    listings = []
                    results["failed"] += 1

                raw_by_source[scraper.source_name] = listings
                logger.info(
                    "orchestrator.source_scraped source=%s count=%d",
                    scraper.source_name, len(listings),
                )

        return raw_by_source

    def _safe_scrape(self, scraper) -> list[dict]:
        """
        Run one scraper, catching all exceptions.
        A broken scraper should never crash the pipeline.
        """
        try:
            return scraper.scrape() or []
        except Exception as exc:
            logger.error(
                "orchestrator.scraper_failed source=%s error=%s",
                scraper.source_name, exc,
            )
            return []

    def _process_one(
        self,
        listing: dict,
        db,
        existing_hashes: set[str],
    ) -> str:
        """
        Process one cleaned listing:
        - Compute fingerprint
        - Check against in-memory hash set (fast)
        - INSERT new or UPDATE existing
        - Extract and save skills

        Returns: "inserted" | "updated" | "skipped"
        """
        fingerprint = self.deduplicator.generate_hash(
            listing.get("title", ""),
            listing.get("company", ""),
            listing.get("location", ""),
        )

        if fingerprint in existing_hashes:
            # Job exists — update mutable fields only
            existing = self.deduplicator.is_duplicate(fingerprint, db)
            if not existing:
                return "skipped"

            new_desc = listing.get("description", "")
            if new_desc and len(new_desc) > len(existing.description or ""):
                existing.description = new_desc

            existing.is_active = True
            existing.updated_at = datetime.utcnow()
            db.add(existing)
            db.commit()
            self._save_skills(existing.id, existing.description or "", db, title=existing.title or "")
            return "updated"

        # Guard: skip listings that somehow passed cleaner with empty title
        # Prevents LLM being called with title="" which wastes API quota
        title = listing.get("title", "").strip()
        if not title:
            logger.warning("orchestrator.skip_empty_title listing=%s", str(listing)[:80])
            return "skipped"

        # New job — extract skills then insert
        skill_result = self.extractor.extract(
            text=listing.get("description", ""),
            title=listing.get("title", ""),
        )

        internship = Internship(
            title=listing["title"],
            company=listing["company"],
            location=listing["location"],
            description=listing["description"],
            application_url=listing["application_url"],
            source=listing.get("source", "unknown"),
            posted_date=listing.get("posted_date"),
            salary_range=listing.get("salary_range"),
            duplicate_hash=fingerprint,
            required_skills=skill_result["skills"],
            # embedding intentionally NOT set here — done by embedding_pipeline.py
        )
        db.add(internship)
        db.commit()
        db.refresh(internship)

        # Save to InternshipSkill table (used by recommendation engine)
        self._save_skills(internship.id, skill_result["skills"], db)

        # Add to in-memory set so subsequent jobs in this run don't re-insert
        existing_hashes.add(fingerprint)

        logger.debug(
            "orchestrator.inserted title=%s company=%s skills=%d",
            internship.title[:40], internship.company[:30], len(skill_result["skills"]),
        )
        return "inserted"

    def _save_skills(
        self,
        internship_id: int,
        skills_or_description,
        db,
        title: str = "",
    ) -> None:
        """
        Write skills to InternshipSkill table.
        Accepts either a list of skill strings OR a description string
        (for the update path where we re-extract from description).
        title is passed so extractor can skip LLM for non-tech jobs.
        """
        # Delete existing skills for this internship first
        db.query(InternshipSkill).filter(
            InternshipSkill.internship_id == internship_id
        ).delete()

        if isinstance(skills_or_description, list):
            skills = skills_or_description
        else:
            # Re-extract from description text — pass title to avoid LLM on non-tech jobs
            result = self.extractor.extract(text=skills_or_description, title=title)
            skills = result["skills"]

        for skill in skills:
            db.add(InternshipSkill(
                internship_id=internship_id,
                skill_name=skill,
            ))
        db.commit()