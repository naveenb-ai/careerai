"""
app/scraper/run.py

Entry point for the scraping pipeline.
Called from main.py startup check and can be run manually.

Two-phase execution:
  Phase 1: Scrape + clean + extract skills + write to DB
  Phase 2: Embed all un-embedded internships

These are separate so if embedding fails, scraped data is already saved.
You can re-run embedding independently: python -m app.scraper.run --embed-only
"""
import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def run_scraper():
    """Phase 1: Scrape all sources."""
    from app.scraper.orchestrator import ScraperOrchestrator
    try:
        from app.config import settings
        groq_key = settings.GROQ_API_KEY
    except Exception:
        groq_key = None

    orchestrator = ScraperOrchestrator(groq_api_key=groq_key)
    logger.info("scraper.start")
    t = time.time()
    results = orchestrator.scrape_all()
    elapsed = round(time.time() - t, 1)
    logger.info(
        "scraper.complete elapsed=%ss inserted=%d updated=%d skipped=%d failed=%d",
        elapsed,
        results["inserted"],
        results["updated"],
        results["skipped"],
        results["failed"],
    )
    for source, stats in results.get("sources", {}).items():
        logger.info("scraper.source source=%s stats=%s", source, stats)
    return results


def run_embedding():
    """Phase 2: Embed all un-embedded internships."""
    from app.scraper.utils.embedding_pipeline import run_embedding_pipeline
    logger.info("embedding_pipeline.start")
    t = time.time()
    result = run_embedding_pipeline()
    elapsed = round(time.time() - t, 1)
    logger.info(
        "embedding_pipeline.complete elapsed=%ss embedded=%d failed=%d",
        elapsed, result["embedded"], result["failed"],
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="CareerAI scraper pipeline")
    parser.add_argument(
        "--embed-only",
        action="store_true",
        help="Skip scraping, only run embedding pipeline on existing un-embedded jobs",
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Only scrape and store jobs, skip embedding",
    )
    args = parser.parse_args()

    if args.embed_only:
        run_embedding()
    elif args.scrape_only:
        run_scraper()
    else:
        # Default: run both phases
        scrape_results = run_scraper()
        if scrape_results["inserted"] > 0 or True:
            # Always run embedding to catch any jobs that failed to embed previously
            run_embedding()


if __name__ == "__main__":
    main()