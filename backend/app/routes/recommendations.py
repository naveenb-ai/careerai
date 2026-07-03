import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.internship import Internship
from app.models.internship_skill import InternshipSkill
from app.models.recommendation import Recommendation
from app.models.resume import Resume
from app.models.skill import Skill
from app.schemas.recommendation import (
    RecommendationItem,
    RecommendationsResponse,
    RefreshResponse,
    SkillGapItem,
    SkillGapResponse,
)
from app.services.auth_service import AuthService
from app.services.recommendation_engine import RecommendationEngine
from app.services.embedding_service import normalize_score

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])
security = HTTPBearer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_display_score(raw_percentage: float) -> float:
    """
    Convert raw composite score (0–100) to a user-friendly display score (50–100).

    WHY: all-MiniLM cosine similarity peaks around 0.3–0.5 for related but
    non-identical texts. A composite score of 58% looks like a C-grade to users
    even when it's actually a strong match. We map the realistic range to 50–100
    so scores feel meaningful.

    Uses the existing normalize_score() from embedding_service which maps
    0.0–0.45 cosine range → 50–100 display. We divide by 100 first since
    normalize_score() expects a 0–1 input.
    """
    raw_0_to_1 = raw_percentage / 100.0
    return normalize_score(raw_0_to_1, min_val=0.0, max_val=0.85)


def _derive_match_label(display_score: float) -> str:
    """Derive label from normalized display score (50–100 range)."""
    if display_score >= 88:
        return "Excellent Match"
    if display_score >= 78:
        return "Strong Match"
    if display_score >= 68:
        return "Good Match"
    if display_score >= 58:
        return "Partial Match"
    return "Low Match"


def _get_skill_names_for_internship(db: Session, internship_id: int) -> list[str]:
    """Fetch required skills for one internship from InternshipSkill table."""
    rows = (
        db.query(InternshipSkill.skill_name)
        .filter(InternshipSkill.internship_id == internship_id)
        .all()
    )
    return [row[0].strip().lower() for row in rows if row[0]]


def _get_user_skill_names(db: Session, user_id: int) -> list[str]:
    """Fetch user's skills as a normalized set."""
    rows = db.query(Skill.skill_name).filter(Skill.user_id == user_id).all()
    return [row[0].strip().lower() for row in rows if row[0]]


def _compute_matched_missing(
    user_skills: list[str], required_skills: list[str]
) -> tuple[list[str], list[str]]:
    """
    Fast set-based skill match for display purposes.
    We use exact match here (not embedding similarity) because:
    - This runs at READ time on every GET request
    - Embedding similarity already ran at REFRESH time and produced the score
    - For display, exact match is sufficient and instant
    """
    user_set = set(user_skills)
    matched = [s for s in required_skills if s in user_set]
    missing = [s for s in required_skills if s not in user_set]
    return matched, missing


def _build_recommendation_item(
    rec: Recommendation,
    internship: Internship,
    user_skills: list[str],
    db: Session,
) -> RecommendationItem:
    """Build a RecommendationItem from a DB Recommendation row + its Internship."""
    required_skills = _get_skill_names_for_internship(db, internship.id)
    matched, missing = _compute_matched_missing(user_skills, required_skills)

    raw_pct = rec.match_percentage or 0.0
    display = _normalize_display_score(raw_pct)
    label = _derive_match_label(display)

    return RecommendationItem(
        internship_id=rec.internship_id,
        title=internship.title or "",
        company=internship.company or "",
        location=internship.location or "",
        application_url=internship.application_url or "",
        similarity_score=round(rec.similarity_score or 0.0, 4),
        match_percentage=round(raw_pct, 1),
        display_score=round(display, 1),
        matched_skills=matched,
        missing_skills=missing,
        match_label=label,
    )


# ---------------------------------------------------------------------------
# GET /api/recommendations
# Reads from DB cache — fast, always available.
# Run POST /refresh to recompute scores.
# ---------------------------------------------------------------------------

@router.get("", response_model=RecommendationsResponse)
async def get_recommendations(
    limit: int = Query(default=20, ge=1, le=20),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    t_start = time.time()

    try:
        user = AuthService.verify_token(db, credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    resume = db.query(Resume).filter(Resume.user_id == user.id).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No resume found. Upload a resume to get recommendations.",
        )

    # FIX: use joinedload to fetch recommendations + internships in ONE query
    # instead of N+1 individual internship lookups
    saved_recs = (
        db.query(Recommendation)
        .filter(Recommendation.user_id == user.id)
        .options(joinedload(Recommendation.internship))
        .order_by(Recommendation.match_percentage.desc())
        .limit(limit)
        .all()
    )

    if not saved_recs:
        # No cached recommendations — tell frontend to call /refresh
        return RecommendationsResponse(
            recommendations=[],
            total=0,
            generated_at=datetime.utcnow().isoformat(),
        )

    # Fetch user skills once — reused for all recommendations
    user_skills = _get_user_skill_names(db, user.id)

    items = []
    for rec in saved_recs:
        if not rec.internship:
            continue
        item = _build_recommendation_item(rec, rec.internship, user_skills, db)
        items.append(item)

    elapsed = round((time.time() - t_start) * 1000)
    logger.info(
        "recommendations.get user_id=%d count=%d elapsed_ms=%d",
        user.id, len(items), elapsed,
    )

    return RecommendationsResponse(
        recommendations=items,
        total=len(items),
        generated_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# POST /api/recommendations/refresh
# Runs the full recommendation engine, recomputes scores, saves to DB.
# Called when: user uploads new resume, user adds skills, manual refresh.
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=RefreshResponse)
async def refresh_recommendations(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    t_start = time.time()

    try:
        user = AuthService.verify_token(db, credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    resume = db.query(Resume).filter(Resume.user_id == user.id).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No resume found. Upload a resume to get recommendations.",
        )

    # Run the full multi-agent scoring pipeline
    engine = RecommendationEngine(db)
    result = engine.refresh_for_user(user.id)
    count = result.get("recommendations", 0)

    # Now read back what was saved (same pattern as GET — consistent response)
    saved_recs = (
        db.query(Recommendation)
        .filter(Recommendation.user_id == user.id)
        .options(joinedload(Recommendation.internship))
        .order_by(Recommendation.match_percentage.desc())
        .limit(20)
        .all()
    )

    user_skills = _get_user_skill_names(db, user.id)

    items = []
    for rec in saved_recs:
        if not rec.internship:
            continue
        item = _build_recommendation_item(rec, rec.internship, user_skills, db)
        items.append(item)

    elapsed = round((time.time() - t_start) * 1000)
    logger.info(
        "recommendations.refresh user_id=%d scored=%d returned=%d elapsed_ms=%d",
        user.id, count, len(items), elapsed,
    )

    return RefreshResponse(
        recommendations=items,
        count=len(items),
        message=f"Recommendations refreshed. Found {len(items)} matches.",
    )


# ---------------------------------------------------------------------------
# GET /api/recommendations/skill-gap
#
# Analyzes the user's top recommendations and tells them:
# - Which skills they're missing most often (prioritized)
# - Which skills they already have that are in demand
# - Actionable priority ranking
#
# This runs entirely from DB + user skills — no engine call needed.
# ---------------------------------------------------------------------------

@router.get("/skill-gap", response_model=SkillGapResponse)
async def get_skill_gap(
    top_n: int = Query(default=10, ge=3, le=20, description="Analyze top N recommendations"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    try:
        user = AuthService.verify_token(db, credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    # Get user's top N recommendations from DB
    top_recs = (
        db.query(Recommendation)
        .filter(Recommendation.user_id == user.id)
        .order_by(Recommendation.match_percentage.desc())
        .limit(top_n)
        .all()
    )

    if not top_recs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recommendations found. Run /refresh first.",
        )

    user_skills = set(_get_user_skill_names(db, user.id))

    # Analyze skill requirements across all top recommendations
    # missing_tracker: skill → list of match_percentages of jobs that need it
    missing_tracker: dict[str, list[float]] = defaultdict(list)
    strong_tracker: dict[str, int] = defaultdict(int)

    for rec in top_recs:
        required = _get_skill_names_for_internship(db, rec.internship_id)
        score = rec.match_percentage or 0.0

        for skill in required:
            if skill in user_skills:
                strong_tracker[skill] += 1
            else:
                missing_tracker[skill].append(score)

    # Build SkillGapItems — ranked by frequency × average relevance
    gap_items: list[SkillGapItem] = []
    for skill, scores in missing_tracker.items():
        frequency = len(scores)
        relevance = round(sum(scores) / len(scores) / 100.0, 3)  # normalize to 0–1

        # Priority logic:
        # High   = missing from 3+ jobs OR from a high-scoring match (>70%)
        # Medium = missing from 2 jobs
        # Low    = missing from only 1 job
        if frequency >= 3 or (frequency >= 1 and max(scores) > 70):
            priority = "High"
        elif frequency == 2:
            priority = "Medium"
        else:
            priority = "Low"

        gap_items.append(SkillGapItem(
            skill=skill,
            frequency=frequency,
            relevance=relevance,
            priority=priority,
        ))

    # Sort: High priority first, then by frequency desc, then relevance desc
    priority_order = {"High": 0, "Medium": 1, "Low": 2}
    gap_items.sort(key=lambda x: (priority_order[x.priority], -x.frequency, -x.relevance))

    # Strong skills = user skills that appear in 2+ top matches
    strong_skills = [
        skill for skill, count in strong_tracker.items() if count >= 2
    ]
    strong_skills.sort(key=lambda s: -strong_tracker[s])

    # Human-readable summary
    high_priority = [g for g in gap_items if g.priority == "High"]
    if high_priority:
        top_missing = ", ".join(g.skill for g in high_priority[:3])
        message = (
            f"To improve your matches, focus on: {top_missing}. "
            f"These appear in {high_priority[0].frequency}+ of your top opportunities."
        )
    elif gap_items:
        message = "You're well-matched for your top opportunities. A few skills could improve your reach."
    else:
        message = "Great profile! You already have all the key skills for your top matches."

    return SkillGapResponse(
        missing_skills=gap_items,
        strong_skills=strong_skills[:10],
        top_match_count=len(top_recs),
        message=message,
    )


# ---------------------------------------------------------------------------
# POST /api/recommendations/explain
# Returns AI-generated explanation for a specific recommendation.
# Called on-demand (user clicks "Why this match?") — not on every load.
# ---------------------------------------------------------------------------

@router.post("/explain/{internship_id}", response_model=dict)
async def explain_recommendation(
    internship_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    try:
        user = AuthService.verify_token(db, credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    # Verify this recommendation exists for this user
    rec = (
        db.query(Recommendation)
        .filter(
            Recommendation.user_id == user.id,
            Recommendation.internship_id == internship_id,
        )
        .first()
    )
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found.",
        )

    internship = db.query(Internship).filter(Internship.id == internship_id).first()
    if not internship:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Internship not found.")

    # Build context for explanation
    user_skills = _get_user_skill_names(db, user.id)
    required_skills = _get_skill_names_for_internship(db, internship_id)
    matched, missing = _compute_matched_missing(user_skills, required_skills)

    # Fetch experience and projects for richer explanation
    from app.models.experience import Experience
    from app.models.project import Project

    experiences = db.query(Experience).filter(Experience.user_id == user.id).all()
    projects = db.query(Project).filter(Project.user_id == user.id).all()

    user_experience = "; ".join(
        f"{e.role} at {e.company}" for e in experiences if e.role
    )
    user_projects = "; ".join(p.name for p in projects if p.name)

    from app.services.recommendation_engine import explain_match

    explanation = explain_match(
        internship_title=internship.title or "",
        internship_company=internship.company or "",
        user_skills=", ".join(user_skills),
        matched_skills=matched,
        missing_skills=missing,
        user_experience=user_experience,
        user_projects=user_projects,
    )

    display = _normalize_display_score(rec.match_percentage or 0.0)

    return {
        "internship_id": internship_id,
        "title": internship.title,
        "company": internship.company,
        "display_score": round(display, 1),
        "match_label": _derive_match_label(display),
        "matched_skills": matched,
        "missing_skills": missing,
        **explanation,   # match_reasons, tip from LLM
    }