"""
app/scraper/utils/cleaner.py  ← NEW FILE

Cleans raw scraper output before skill extraction and DB write.

Pipeline position:
  Scraper (raw dict) → Cleaner → SkillExtractor → Deduplicator → DB

Responsibilities:
- Strip HTML tags from description
- Normalize whitespace
- Standardize location strings
- Validate required fields (title, company, description)
- Truncate oversized fields to DB column limits
- Return None for listings that fail validation (pipeline skips them)
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Matches common HTML tags
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Collapses multiple whitespace/newlines into single space
_WHITESPACE_RE = re.compile(r"\s+")
# Matches HTML entities like &amp; &nbsp; &lt;
_HTML_ENTITY_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")

# Location normalization — map common abbreviations/variants to canonical form
_LOCATION_ALIASES: dict[str, str] = {
    "wfh":          "Remote",
    "work from home": "Remote",
    "remote/wfh":   "Remote",
    "pan india":    "India",
    "anywhere":     "Remote",
    "bangalore":    "Bengaluru",
    "bombay":       "Mumbai",
    "new delhi":    "Delhi",
}


class JobCleaner:
    """
    Cleans a single raw job dict returned by a scraper.

    Usage:
        cleaner = JobCleaner()
        clean = cleaner.clean(raw_listing)
        if clean is None:
            continue  # invalid listing, skip it
    """

    # Minimum description length — listings shorter than this are useless
    MIN_DESCRIPTION_LENGTH = 30
    # DB column limits
    MAX_TITLE_LENGTH = 255
    MAX_COMPANY_LENGTH = 255
    MAX_LOCATION_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 10_000
    MAX_URL_LENGTH = 500
    MAX_SALARY_LENGTH = 100

    def clean(self, raw: dict) -> Optional[dict]:
        """
        Clean and validate a raw scraper listing.
        Returns cleaned dict or None if listing is invalid/useless.
        """
        title   = self._clean_text(raw.get("title", ""))
        company = self._clean_text(raw.get("company", ""))
        location = self._normalize_location(raw.get("location", ""))
        description = self._clean_description(raw.get("description", ""))
        apply_link  = self._clean_url(raw.get("application_url") or raw.get("apply_link", ""))

        # Validate required fields — skip listing if any are missing
        if not title:
            logger.debug("cleaner.skip reason=missing_title raw=%s", str(raw)[:80])
            return None
        if not company:
            logger.debug("cleaner.skip reason=missing_company title=%s", title[:50])
            return None
        if not description or len(description) < self.MIN_DESCRIPTION_LENGTH:
            logger.debug("cleaner.skip reason=description_too_short title=%s", title[:50])
            return None
        if not apply_link:
            logger.debug("cleaner.skip reason=missing_url title=%s", title[:50])
            return None

        return {
            "title":           title[:self.MAX_TITLE_LENGTH],
            "company":         company[:self.MAX_COMPANY_LENGTH],
            "location":        location[:self.MAX_LOCATION_LENGTH],
            "description":     description[:self.MAX_DESCRIPTION_LENGTH],
            "application_url": apply_link[:self.MAX_URL_LENGTH],
            "source":          str(raw.get("source", "unknown"))[:50],
            "salary_range":    self._clean_text(raw.get("salary_range") or "")[:self.MAX_SALARY_LENGTH] or None,
            "duration":        self._clean_text(raw.get("duration") or "")[:100] or None,
            "posted_date":     raw.get("posted_date"),  # pass through — already None or date
        }

    def clean_batch(self, raw_listings: list[dict]) -> list[dict]:
        """
        Clean a list of raw listings. Skips invalid ones.
        Returns only valid, cleaned listings.
        """
        cleaned = []
        skipped = 0
        for raw in raw_listings:
            result = self.clean(raw)
            if result is not None:
                cleaned.append(result)
            else:
                skipped += 1

        logger.info(
            "cleaner.batch_complete input=%d valid=%d skipped=%d",
            len(raw_listings), len(cleaned), skipped,
        )
        return cleaned

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clean_text(self, value: str) -> str:
        """Strip HTML, collapse whitespace, strip edges."""
        if not value:
            return ""
        text = _HTML_TAG_RE.sub(" ", str(value))
        text = _HTML_ENTITY_RE.sub(" ", text)
        text = _WHITESPACE_RE.sub(" ", text)
        return text.strip()

    def _clean_description(self, value: str) -> str:
        """Clean description — same as _clean_text but preserves more structure."""
        if not value:
            return ""
        # Replace block-level tags with newlines before stripping
        text = re.sub(r"<(?:br|p|div|li|tr)[^>]*>", "\n", str(value), flags=re.IGNORECASE)
        text = _HTML_TAG_RE.sub(" ", text)
        text = _HTML_ENTITY_RE.sub(" ", text)
        # Collapse multiple newlines to max 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Collapse spaces within lines
        lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
        return "\n".join(line for line in lines if line).strip()

    def _normalize_location(self, value: str) -> str:
        """Normalize location strings to canonical form."""
        if not value:
            return "India"  # default for Indian job sites
        cleaned = self._clean_text(value)
        lower = cleaned.lower().strip()
        # Check alias map
        for alias, canonical in _LOCATION_ALIASES.items():
            if alias in lower:
                return canonical
        # Title-case the result
        return cleaned.title() if cleaned else "India"

    def _clean_url(self, value: str) -> str:
        """Basic URL validation and cleaning."""
        if not value:
            return ""
        url = str(value).strip()
        if not url.startswith(("http://", "https://")):
            return ""
        return url