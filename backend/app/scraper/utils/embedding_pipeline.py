"""
app/scraper/utils/embedding_pipeline.py

Embeds all internships that don't have an embedding yet.
Runs AFTER the scraper, not during it.

Why separate:
- Scraper should be fast and not block on model inference
- If embedding fails, scraped data is already saved safely
- Can be re-run independently: python -m app.scraper.run --embed-only
"""
import logging

from sqlalchemy import text

from app.database import SessionLocal
from app.services.embedding_service import embed_internship

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 16


class EmbeddingPipeline:

    def run(self) -> dict:
        db = SessionLocal()
        try:
            return self._run_pipeline(db)
        finally:
            db.close()

    def _run_pipeline(self, db) -> dict:
        # Raw SQL — avoids ORM/pgvector type issues entirely.
        # Fetches only the fields we need (no vector data loaded).
        rows = db.execute(
            text("""
                SELECT id, title, company, description, location
                FROM internships
                WHERE embedding IS NULL
                  AND is_active = true
                ORDER BY id
            """)
        ).fetchall()

        total = len(rows)
        if total == 0:
            logger.info("embedding_pipeline.nothing_to_do")
            return {"embedded": 0, "failed": 0}

        logger.info(
            "embedding_pipeline.start count=%d batch_size=%d",
            total, EMBED_BATCH_SIZE,
        )

        embedded = 0
        failed = 0

        for batch_start in range(0, total, EMBED_BATCH_SIZE):
            batch = rows[batch_start: batch_start + EMBED_BATCH_SIZE]
            b_ok, b_fail = self._embed_batch(batch, db)
            embedded += b_ok
            failed += b_fail
            logger.info(
                "embedding_pipeline.progress done=%d/%d embedded=%d failed=%d",
                min(batch_start + EMBED_BATCH_SIZE, total), total, b_ok, b_fail,
            )

        logger.info(
            "embedding_pipeline.complete total=%d embedded=%d failed=%d",
            total, embedded, failed,
        )
        return {"embedded": embedded, "failed": failed}

    def _embed_batch(self, rows, db) -> tuple[int, int]:
        embedded = 0
        failed = 0

        for row in rows:
            internship_id, title, company, description, location = row
            try:
                vector = embed_internship(
                    title=title or "",
                    company=company or "",
                    description=description or "",
                    location=location or "",
                )
                # Write via raw SQL — pgvector expects the list cast to ::vector
                db.execute(
                    text(
                        "UPDATE internships SET embedding = CAST(:vec AS vector) WHERE id = :id"
                    ),
                    {"vec": str(vector), "id": internship_id},
                )
                embedded += 1
            except Exception as exc:
                logger.error(
                    "embedding_pipeline.embed_failed id=%d title=%s error=%s",
                    internship_id, (title or "")[:40], exc,
                )
                failed += 1

        if embedded > 0:
            db.commit()

        return embedded, failed


def run_embedding_pipeline() -> dict:
    return EmbeddingPipeline().run()