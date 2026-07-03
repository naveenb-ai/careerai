import os
import threading
import subprocess
import sys
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.config import settings
from app.database import Base, engine

# Import models so SQLAlchemy metadata includes all tables before create_all()
import app.models  # noqa: F401

from app.routes import auth
from app.routes.agent import router as agent_router
from app.routes.applications import router as applications_router
from app.routes.bolt import router as bolt_router
from app.routes.career import router as career_router
from app.routes.drafts import router as drafts_router
from app.routes.internships import router as internships_router
from app.routes.notifications import router as notifications_router
from app.routes.recommendations import router as recommendations_router
from app.routes.resume import router as resume_router
from app.routes.resume_analysis import router as resume_analysis_router
from app.routes.resume_agent import router as resume_agent_router
from app.routes.interview import router as interview_router
from app.routes.linkedin import router as linkedin_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Career Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(internships_router, prefix="/api")
app.include_router(recommendations_router, prefix="/api")
app.include_router(career_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(bolt_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(applications_router, prefix="/api")
app.include_router(drafts_router, prefix="/api")
app.include_router(resume_router, prefix="/api")
app.include_router(resume_analysis_router, prefix="/api")
app.include_router(resume_agent_router, prefix="/api")
app.include_router(interview_router, prefix="/api")
app.include_router(linkedin_router, prefix="/api")


def run_scraper_if_empty():
    """Run scraper on startup if no internships exist."""
    try:
        from app.database import SessionLocal
        from app.models.internship import Internship
        db: Session = SessionLocal()
        count = db.query(Internship).count()
        db.close()
        if count == 0:
            print("No internships found - running scraper automatically...")
            subprocess.Popen(
                [sys.executable, "-m", "app.scraper.run"],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
        else:
            print(f"Internships already loaded: {count} found.")
    except Exception as e:
        print(f"Scraper startup check failed: {e}")


def preload_embedding_model():
    """
    Load the sentence-transformer model into memory at startup.

    WHY: The model loads from disk on its first use (~15-20s).
    Without this, the first user after every server restart waits 20s
    for their request to complete while the model loads.
    With this, the model is ready before any request arrives.

    Also pre-warms the embedding cache with the most common tech skills
    so the first few real requests skip even more model calls.
    """
    try:
        print("Preloading embedding model...")
        from app.services.embedding_service import get_model, embed_text
        get_model()  # loads model into memory now

        # Pre-warm cache with skills that appear in almost every job posting.
        # These will be cache HITs on the very first recommendation request.
        COMMON_SKILLS = [
            "python", "javascript", "react", "node", "sql", "java",
            "aws", "docker", "git", "css", "html", "typescript",
            "machine learning", "data science", "django", "flask",
            "mongodb", "postgresql", "rest", "api", "excel",
        ]
        from app.services.recommendation_engine import _embedding_manager
        for skill in COMMON_SKILLS:
            _embedding_manager.get_embedding(skill)

        print(f"Embedding model ready. Pre-warmed {len(COMMON_SKILLS)} common skills.")
    except Exception as e:
        # Never crash startup — just warn. Embeddings will load lazily on first request.
        print(f"Warning: embedding model preload failed: {e}")


@app.on_event("startup")
async def startup_event():
    # Run scraper check in background thread (may take time, shouldn't block startup)
    scraper_thread = threading.Thread(target=run_scraper_if_empty, daemon=True)
    scraper_thread.start()

    # Preload embedding model in background thread so startup is non-blocking
    # but model is ready well before the first user request arrives
    model_thread = threading.Thread(target=preload_embedding_model, daemon=True)
    model_thread.start()


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    # Include model status in health check so you can verify it loaded
    try:
        from app.services.embedding_service import _model
        model_status = "loaded" if _model is not None else "not_loaded"
    except Exception:
        model_status = "unknown"

    return {
        "status": "healthy",
        "database": db_status,
        "embedding_model": model_status,
        "version": "1.0.0",
    }