"""
app/scraper/sources/internshala.py

Playwright-based scraper for Internshala.
Gets 60-100 listings across 5 tech categories.
"""
import logging
import time
from app.scraper.sources.base import BaseScraper

logger = logging.getLogger(__name__)

SEARCH_URLS = [
    "https://internshala.com/internships/python-internship/",
    "https://internshala.com/internships/web-development-internship/",
    "https://internshala.com/internships/data-science-internship/",
    "https://internshala.com/internships/machine-learning-internship/",
    "https://internshala.com/internships/java-internship/",
]


class IntershalaScraper(BaseScraper):
    source_name = "internshala"
    base_url = "https://internshala.com/internships/"

    def scrape(self) -> list[dict]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error(
                "internshala.playwright_missing — run: pip install playwright && playwright install chromium"
            )
            return []

        listings = []
        seen_urls: set[str] = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            for url in SEARCH_URLS:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    try:
                        page.wait_for_selector(".individual_internship", timeout=8000)
                    except Exception:
                        logger.warning("internshala.no_cards url=%s", url)
                        continue

                    cards = page.query_selector_all(".individual_internship")
                    logger.info("internshala.cards_found count=%d url=%s", len(cards), url)

                    for card in cards[:20]:
                        try:
                            title_el   = card.query_selector(".job-internship-name")
                            company_el = card.query_selector(".company-name")
                            loc_el     = (
                                card.query_selector(".location_link")
                                or card.query_selector(".locations_name")
                                or card.query_selector(".locations")
                            )
                            stipend_el = card.query_selector(".stipend_status")
                            link_el    = (
                                card.query_selector("a.view_detail_button")
                                or card.query_selector("a[href*='/internship/']")
                            )
                            # Skills listed on card (Internshala shows skill tags)
                            skill_els = card.query_selector_all(".round_tabs_container span, .skill_container span, [class*='skill'] span")

                            title   = title_el.inner_text().strip() if title_el   else ""
                            company = company_el.inner_text().strip() if company_el else ""

                            if not title or not company:
                                continue

                            href = link_el.get_attribute("href") if link_el else None
                            full_url = (
                                f"https://internshala.com{href}"
                                if href and href.startswith("/")
                                else href or url
                            )

                            if full_url in seen_urls:
                                continue
                            seen_urls.add(full_url)

                            location = loc_el.inner_text().strip() if loc_el else "India"
                            stipend  = stipend_el.inner_text().strip() if stipend_el else None

                            # Build clean description from card text
                            # Extract the detail section (below title/company/location)
                            detail_el = card.query_selector(".internship_other_details_container, .internship-listing-details")
                            if detail_el:
                                description = detail_el.inner_text().strip()[:800]
                            else:
                                # Fallback: full card text but strip the header noise
                                raw = card.inner_text().strip()
                                # Remove the first 3 lines (title, company, location)
                                lines = [l.strip() for l in raw.split("\n") if l.strip()]
                                description = " ".join(lines[3:])[:800]

                            # Append skill tags to description so extractor sees them
                            if skill_els:
                                skill_text = " ".join(
                                    s.inner_text().strip() for s in skill_els if s.inner_text().strip()
                                )
                                description = f"{description}\nSkills: {skill_text}"

                            listings.append({
                                "title":           title,
                                "company":         company,
                                "location":        location,
                                "description":     description,
                                "application_url": full_url,
                                "salary_range":    stipend,
                                "posted_date":     None,
                                "source":          self.source_name,
                            })
                        except Exception as exc:
                            logger.debug("internshala.card_error error=%s", exc)
                            continue

                    time.sleep(2)

                except Exception as exc:
                    logger.error("internshala.page_error url=%s error=%s", url, type(exc).__name__)
                    continue

            browser.close()

        logger.info("internshala.complete total=%d", len(listings))
        return listings