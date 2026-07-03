from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class RecommendationItem(BaseModel):
    internship_id: int
    title: str
    company: str
    location: str
    application_url: str
    similarity_score: float
    match_percentage: float       # raw composite score × 100 (stored in DB, used for sorting)
    display_score: float          # normalized score for UI display (50–100 range, like LinkedIn)
    matched_skills: list[str]
    missing_skills: list[str]
    match_label: str
    signal_breakdown: Optional[dict] = None  # per-dimension scores, shown in detail view

    class Config:
        from_attributes = True


class RecommendationsResponse(BaseModel):
    recommendations: list[RecommendationItem]
    total: int
    generated_at: str             # ISO string — simpler than datetime for frontend


class RefreshResponse(BaseModel):
    recommendations: list[RecommendationItem]
    count: int
    message: str


# ---------------------------------------------------------------------------
# Skill Gap schemas — for the new GET /recommendations/skill-gap endpoint
# ---------------------------------------------------------------------------

class SkillGapItem(BaseModel):
    skill: str                    # skill name the user is missing
    frequency: int                # how many of their top matches require this skill
    relevance: float              # average match score of jobs requiring this skill (0–1)
    priority: str                 # "High" / "Medium" / "Low" — based on frequency + relevance


class SkillGapResponse(BaseModel):
    missing_skills: list[SkillGapItem]   # ranked by priority
    strong_skills: list[str]             # skills user already has that appear in top matches
    top_match_count: int                 # how many recommendations were analyzed
    message: str                         # human-readable summary