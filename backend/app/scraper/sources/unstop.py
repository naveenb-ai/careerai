"""
app/scraper/sources/unstop.py

Direct API scraper — no Playwright, no HTML parsing.
Unstop exposes a public JSON API that returns structured job data
including pre-extracted skills, full descriptions, and company info.

API endpoint discovered via DevTools network inspection.
Paginates through multiple pages to maximize job coverage.
"""
import logging
import time
import re
from typing import Optional
import requests
from app.scraper.sources.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://unstop.com/api/public/opportunity/search-result"

# Fetch multiple pages across different filters for better coverage
QUERIES = [
    {"opportunity": "internships", "oppstatus": "open", "domain": ""},
    {"opportunity": "internships", "oppstatus": "open", "domain": "technology"},
    {"opportunity": "internships", "oppstatus": "open", "domain": "engineering"},
    {"opportunity": "internships", "oppstatus": "open", "domain": "data-science"},
]

PER_PAGE = 25
MAX_PAGES = 3   # 3 pages × 25 jobs × 4 queries = up to 300 jobs max

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    text = _HTML_TAG_RE.sub(" ", html or "")
    return _WHITESPACE_RE.sub(" ", text).strip()


class UnstopScraper(BaseScraper):
    source_name = "unstop"
    base_url = "https://unstop.com/internships"

    # Override rate_limit_seconds from base — API can handle faster requests
    rate_limit_seconds = 1.5

    def scrape(self) -> list[dict]:
        listings = []
        seen_ids: set[int] = set()

        session = requests.Session()
        session.headers.update({
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer":         "https://unstop.com/internships",
            "Origin":          "https://unstop.com",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        })

        for query in QUERIES:
            for page in range(1, MAX_PAGES + 1):
                params = {
                    **query,
                    "page":             page,
                    "per_page":         PER_PAGE,
                    "sortBy":           "",
                    "orderBy":          "",
                    "filter_condition": "",
                    "undefined":        "true",
                }

                try:
                    response = session.get(
                        API_URL, params=params, timeout=15
                    )

                    if response.status_code != 200:
                        logger.warning(
                            "unstop.api_error status=%d page=%d query=%s",
                            response.status_code, page, query.get("domain", "all"),
                        )
                        break

                    data = response.json()
                    jobs = data.get("data", {}).get("data", [])

                    if not jobs:
                        # No more results for this query
                        break

                    for job in jobs:
                        job_id = job.get("id")
                        if not job_id or job_id in seen_ids:
                            continue
                        seen_ids.add(job_id)

                        parsed = self._parse_job(job)
                        if parsed:
                            listings.append(parsed)

                    logger.info(
                        "unstop.page_scraped domain=%s page=%d jobs=%d total_so_far=%d",
                        query.get("domain") or "all", page, len(jobs), len(listings),
                    )

                    # Stop paginating if we got fewer results than requested
                    if len(jobs) < PER_PAGE:
                        break

                    self.respect_rate_limit()

                except Exception as exc:
                    logger.error(
                        "unstop.request_failed page=%d query=%s error=%s",
                        page, query, type(exc).__name__,
                    )
                    break

        logger.info("unstop.complete total=%d", len(listings))
        return listings

    def _parse_job(self, job: dict) -> Optional[dict]:
        """
        Parse one Unstop API job object into our standard format.

        Key fields from API response:
        - title: job title
        - organisation.name: company name
        - seo_url: full URL to job page
        - details: HTML description (needs stripping)
        - required_skills[].skill_name: pre-tagged skills (huge bonus!)
        - region: "online" / "offline" / city name
        - address_with_country_logo: city/state/country
        """
        try:
            title = (job.get("title") or "").strip()
            if not title:
                return None

            company = (
                job.get("organisation", {}).get("name")
                or "Company"
            ).strip()

            # Location: prefer city from address, fall back to region
            address = job.get("address_with_country_logo", {})
            city    = address.get("city", "").strip()
            state   = address.get("state", "").strip()
            region  = (job.get("region") or "").strip()

            if city:
                location = f"{city}, {state}".strip(", ") if state else city
            elif region and region.lower() not in ("online", ""):
                location = region
            else:
                location = "Remote" if region == "online" else "India"

            # Full URL
            url = (
                job.get("seo_url")
                or job.get("short_url")
                or self.base_url
            )

            # Description: strip HTML from details field
            raw_details = job.get("details") or ""
            description = _strip_html(raw_details)

            # Pre-tagged skills from Unstop — append to description
            # so our SkillExtractor also sees them (belt + suspenders)
            skill_tags = job.get("required_skills", [])
            if skill_tags:
                skill_names = [
                    s.get("skill_name") or s.get("skill", "")
                    for s in skill_tags
                    if isinstance(s, dict)
                ]
                skill_names = [s.strip() for s in skill_names if s.strip()]
                if skill_names:
                    description = f"{description}\nSkills: {', '.join(skill_names)}"

            if not description or len(description) < 20:
                description = f"{title} internship at {company}"

            return {
                "title":           title,
                "company":         company,
                "location":        location,
                "description":     description[:1000],
                "application_url": url,
                "salary_range":    None,  # Unstop API doesn't expose stipend in listing
                "posted_date":     None,
                "source":          self.source_name,
            }

        except Exception as exc:
            logger.debug("unstop.parse_error error=%s job_id=%s", exc, job.get("id"))
            return None