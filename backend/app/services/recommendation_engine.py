import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.experience import Experience
from app.models.internship import Internship
from app.models.internship_skill import InternshipSkill
from app.models.project import Project
from app.models.recommendation import Recommendation
from app.models.resume import Resume
from app.models.skill import Skill
from app.services.embedding_manager import EmbeddingManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton EmbeddingManager — one instance for the entire process lifetime.
#
# WHY: FastAPI creates a new RecommendationEngine(db) per request. Without
# this, each request creates a new EmbeddingManager() with an empty cache,
# making the in-memory cache useless across requests. With a module-level
# singleton, the cache persists for as long as the process runs — embeddings
# for common skills like "python" or "react" are computed exactly once.
# ---------------------------------------------------------------------------
_embedding_manager = EmbeddingManager()


# ---------------------------------------------------------------------------
# Output schema for InternshipRecommendation
# ---------------------------------------------------------------------------

@dataclass
class InternshipRecommendation:
    internship_id: int
    title: str
    company: str
    location: str
    application_url: str
    similarity_score: float
    match_percentage: float
    matched_skills: List[str]
    missing_skills: List[str]
    match_label: str


# ---------------------------------------------------------------------------
# Pydantic schema for LLM explanation output — validates before we trust it
# ---------------------------------------------------------------------------

class ExplanationOutput(BaseModel):
    match_reasons: List[str]
    missing_skills: List[str]
    tip: str


# ---------------------------------------------------------------------------
# FIX 1: EmbeddingCache — avoids recomputing the same embedding twice
#
# WHY: Without this, if a user has 10 skills and you score 50 internships,
# you call the embedding model 10×50 = 500 times for the exact same vectors.
# With this cache, those 10 embeddings are computed once and reused.
# ---------------------------------------------------------------------------

class EmbeddingCache:
    """
    In-memory embedding cache scoped to a single request lifecycle.

    Usage:
        cache = EmbeddingCache(embedding_manager)
        vec = cache.get("python")   # computed once, reused on repeat calls
    """

    def __init__(self, embedding_manager: EmbeddingManager):
        self._manager = embedding_manager
        self._store: Dict[str, List[float]] = {}

    def get(self, text: str) -> List[float]:
        if not text:
            return []
        key = text.strip().lower()
        if key not in self._store:
            self._store[key] = self._manager.get_embedding(key)
        return self._store[key]

    def get_many(self, texts: List[str]) -> List[List[float]]:
        """Batch-fetch embeddings, computing only the ones not yet cached."""
        return [self.get(t) for t in texts if t]


# ---------------------------------------------------------------------------
# FIX 2: JobAnalysisAgent — replaces the hardcoded _build_job_analysis()
#
# WHY: The old version always returned seniority_level=1.0 (hardcoded) and
# had no domain field. This agent infers seniority and domain from available
# data (title + skills + description if present) without requiring an LLM
# call, keeping it fast and free.
# ---------------------------------------------------------------------------

class JobAnalysisAgent:
    """
    Analyzes a job posting and returns structured fields.
    Works from title + skills as primary signal.
    Uses description as a bonus signal when non-empty.
    No LLM call — rule-based inference is fast and sufficient here.
    """

    # Seniority keywords mapped to a numeric level (used in scoring).
    # Level 1.0 = intern/junior, 2.0 = mid, 3.0 = senior
    _SENIORITY_MAP = {
        "intern":       1.0, "internship": 1.0, "trainee": 1.0,
        "junior":       1.2, "entry":      1.2, "entry-level": 1.2,
        "associate":    1.5,
        "mid":          2.0, "mid-level":  2.0, "intermediate": 2.0,
        "senior":       3.0, "sr":         3.0, "lead": 3.0,
        "principal":    3.5, "staff":      3.5,
        "manager":      3.0, "director":   4.0,
    }

    # Domain keywords — maps terms found in title/skills to a domain label
    _DOMAIN_MAP = {
        ("machine learning", "deep learning", "pytorch", "tensorflow",
         "nlp", "computer vision", "ai", "ml"):               "ai_ml",
        ("react", "vue", "angular", "frontend", "css", "html",
         "next.js", "ui", "ux"):                               "frontend",
        ("django", "fastapi", "flask", "node", "backend",
         "rest api", "graphql", "microservices"):              "backend",
        ("aws", "gcp", "azure", "devops", "kubernetes",
         "docker", "ci/cd", "terraform"):                      "devops",
        ("pandas", "numpy", "sql", "data analysis",
         "tableau", "power bi", "spark", "etl"):               "data",
        ("android", "ios", "flutter", "react native",
         "swift", "kotlin"):                                    "mobile",
        ("cybersecurity", "penetration testing", "soc",
         "siem", "ethical hacking"):                           "security",
    }

    def analyze(self, internship: Internship, required_skills: List[str]) -> Dict[str, Any]:
        title = (internship.title or "").lower()
        description = (internship.description or "").lower()
        company = (internship.company or "").lower()

        seniority_level = self._infer_seniority(title, description)
        domain = self._infer_domain(title, required_skills, description)

        # Build a searchable text blob for domain/embedding comparisons
        context_text = self._build_context_text(
            title=internship.title,
            company=internship.company,
            skills=required_skills,
            description=internship.description,
        )

        return {
            "internship_id": internship.id,
            "required_skills": required_skills,
            "seniority_level": seniority_level,   # now actually inferred, not hardcoded
            "domain": domain,
            "context_text": context_text,
        }

    def _infer_seniority(self, title: str, description: str) -> float:
        text = f"{title} {description}"
        for keyword, level in self._SENIORITY_MAP.items():
            if keyword in text:
                return level
        return 1.0  # default: treat as internship/entry level

    def _infer_domain(
        self, title: str, skills: List[str], description: str
    ) -> str:
        combined = f"{title} {description} {' '.join(skills)}".lower()
        for keywords, domain in self._DOMAIN_MAP.items():
            if any(kw in combined for kw in keywords):
                return domain
        return "general"

    def _build_context_text(
        self,
        title: Optional[str],
        company: Optional[str],
        skills: List[str],
        description: Optional[str],
    ) -> str:
        # Use title + skills as the primary signal for embeddings.
        # We intentionally exclude description here even when available:
        #   1. Description text becomes a long, unique cache key that bloats memory.
        #   2. A 300-char description blob creates noisy embeddings that dilute
        #      the clean skill-to-skill similarity signal.
        #   3. The pgvector embedding (computed at ingestion time from full description)
        #      already captures the semantic content of the description — we don't
        #      need to re-embed it here.
        # Result: "react node.js mongodb mern stack developer internship"
        parts = [title or ""] + skills
        return " ".join(p for p in parts if p).lower().strip()


# ---------------------------------------------------------------------------
# FIX 3: MatchScoringAgent — same logic, but now accepts EmbeddingCache
#
# WHY: The original recomputed user embeddings inside every skill-match call.
# Now it accepts a shared cache so user vectors are computed once per request.
# Also: domain_alignment now uses job_analysis["domain"] for better accuracy.
# ---------------------------------------------------------------------------

class MatchScoringAgent:
    """
    Scores a (user_profile, job_analysis) pair on 5 dimensions.
    Accepts an EmbeddingCache to avoid redundant model calls.
    """

    DEFAULT_WEIGHTS = {
        "semantic_similarity": 0.30,
        "skill_coverage":      0.25,
        "skill_depth":         0.20,
        "domain_alignment":    0.15,
        "seniority_alignment": 0.10,
    }
    DEFAULT_SKILL_MATCH_THRESHOLD = 0.70

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        skill_match_threshold: float = DEFAULT_SKILL_MATCH_THRESHOLD,
    ):
        self.weights = self._normalize_weights(weights or self.DEFAULT_WEIGHTS)
        self.skill_match_threshold = max(0.0, min(1.0, skill_match_threshold))
        self.embedding_manager = _embedding_manager  # use process-level singleton

    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        total = sum(weights.values())
        if total <= 0:
            return self.DEFAULT_WEIGHTS.copy()
        return {k: float(v) / total for k, v in weights.items()}

    def score_match(
        self,
        user_profile: Dict[str, Any],
        job_analysis: Dict[str, Any],
        embedding_similarity: float,
        cache: Optional[EmbeddingCache] = None,
    ) -> Dict[str, Any]:
        """
        Compute composite match score.

        Args:
            user_profile:        Output of RecommendationEngine._build_user_profile()
            job_analysis:        Output of JobAnalysisAgent.analyze()
            embedding_similarity: Precomputed pgvector cosine similarity (0–1)
            cache:               Shared EmbeddingCache for this request
        """
        if cache is None:
            cache = EmbeddingCache(self.embedding_manager)

        semantic_similarity = self._clamp(embedding_similarity)

        required_skills = job_analysis.get("required_skills", [])
        matched_skills, missing_skills = self._semantic_skill_match(
            user_skills=user_profile.get("skills", []),
            required_skills=required_skills,
            cache=cache,
        )

        skill_coverage     = self._compute_skill_coverage(required_skills, matched_skills)
        skill_depth        = self._compute_skill_depth(user_profile, matched_skills, required_skills, cache)
        domain_alignment   = self._compute_domain_alignment(user_profile, job_analysis, matched_skills, cache)
        seniority_alignment = self._compute_seniority_alignment(user_profile, job_analysis)

        composite_score = (
            semantic_similarity    * self.weights["semantic_similarity"]
            + skill_coverage       * self.weights["skill_coverage"]
            + skill_depth          * self.weights["skill_depth"]
            + domain_alignment     * self.weights["domain_alignment"]
            + seniority_alignment  * self.weights["seniority_alignment"]
        )
        composite_score = round(self._clamp(composite_score), 4)

        return {
            "internship_id": int(job_analysis.get("internship_id", 0)),
            "composite_score": composite_score,
            "signal_breakdown": {
                "semantic_similarity": round(semantic_similarity, 4),
                "skill_coverage":      round(skill_coverage, 4),
                "skill_depth":         round(skill_depth, 4),
                "domain_alignment":    round(domain_alignment, 4),
                "seniority_alignment": round(seniority_alignment, 4),
            },
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
        }

    # ------------------------------------------------------------------
    # Internal scoring helpers
    # ------------------------------------------------------------------

    def _semantic_skill_match(
        self,
        user_skills: List[Dict[str, Any]],
        required_skills: List[str],
        cache: EmbeddingCache,
    ) -> Tuple[List[str], List[str]]:
        from app.services.embedding_service import cosine_similarity

        user_skill_texts = [
            _normalize(s.get("name")) for s in user_skills if s.get("name")
        ]
        required_skill_texts = [_normalize(s) for s in required_skills if s]

        if not required_skill_texts or not user_skill_texts:
            return [], required_skill_texts

        # FIX: use cache — these were being recomputed 50× per request before
        user_embeddings     = cache.get_many(user_skill_texts)
        required_embeddings = cache.get_many(required_skill_texts)

        matched = []
        for skill_text, req_emb in zip(required_skill_texts, required_embeddings):
            if not req_emb:
                continue
            best = max(
                (cosine_similarity(u_emb, req_emb) for u_emb in user_embeddings if u_emb),
                default=0.0,
            )
            if best >= self.skill_match_threshold:
                matched.append(skill_text)

        missing = [s for s in required_skill_texts if s not in matched]
        return matched, missing

    def _compute_skill_coverage(
        self, required_skills: List[str], matched_skills: List[str]
    ) -> float:
        if not required_skills:
            return 0.0
        return len(matched_skills) / len(required_skills)

    def _compute_skill_depth(
        self,
        user_profile: Dict[str, Any],
        matched_skills: List[str],
        required_skills: List[str],
        cache: EmbeddingCache,
    ) -> float:
        if not matched_skills or not required_skills:
            return 0.0

        matched_ratio    = len(matched_skills) / len(required_skills)
        experience_years = float(user_profile.get("experience_years", 0.0))
        project_relevance = self._compute_project_relevance(user_profile, required_skills, cache)
        experience_factor = min(1.0, experience_years / max(1.0, len(required_skills)))

        w = {"matched_ratio": 0.45, "experience": 0.35, "project_relevance": 0.20}
        return min(1.0, (
            matched_ratio     * w["matched_ratio"]
            + experience_factor * w["experience"]
            + project_relevance * w["project_relevance"]
        ) / sum(w.values()))

    def _compute_project_relevance(
        self,
        user_profile: Dict[str, Any],
        required_skills: List[str],
        cache: EmbeddingCache,
    ) -> float:
        from app.services.embedding_service import cosine_similarity

        project_terms = [
            _normalize(t) for t in user_profile.get("project_technologies", []) if t
        ]
        if not project_terms or not required_skills:
            return 0.0

        # Instead of embedding a joined blob (unique string = always a cache miss),
        # embed each term individually (short strings = mostly cache hits) and
        # average the best similarity per required skill.
        # This reuses cached embeddings for terms like "python", "react", "sql".
        required_embeddings = cache.get_many(required_skills)
        project_embeddings  = cache.get_many(project_terms)

        if not required_embeddings or not project_embeddings:
            return 0.0

        scores = []
        for req_emb in required_embeddings:
            if not req_emb:
                continue
            best = max(
                (cosine_similarity(p_emb, req_emb) for p_emb in project_embeddings if p_emb),
                default=0.0,
            )
            scores.append(best)

        return float(sum(scores) / len(scores)) if scores else 0.0

    def _compute_domain_alignment(
        self,
        user_profile: Dict[str, Any],
        job_analysis: Dict[str, Any],
        matched_skills: List[str],
        cache: EmbeddingCache,
    ) -> float:
        from app.services.embedding_service import cosine_similarity

        required_skills = [
            _normalize(s) for s in job_analysis.get("required_skills", []) if s
        ]
        if not required_skills:
            return 0.0

        # Signal 1: skill overlap ratio (no embedding needed — pure set math)
        # "How much of the job's domain vocabulary does the user already speak?"
        user_skill_set = {
            _normalize(s.get("name")) for s in user_profile.get("skills", []) if s.get("name")
        }
        project_tech_set = {
            _normalize(t) for t in user_profile.get("project_technologies", []) if t
        }
        user_vocab = user_skill_set | project_tech_set | set(matched_skills)
        required_set = set(required_skills)

        if required_set:
            overlap_ratio = len(user_vocab & required_set) / len(required_set)
        else:
            overlap_ratio = 0.0

        # Signal 2: semantic similarity between user skills and required skills
        # Uses individual cached embeddings — no new blob embeddings needed.
        # Each skill like "react", "python" is already in cache from _semantic_skill_match.
        user_terms = [s for s in user_vocab if s]
        if user_terms and required_skills:
            user_embeddings    = cache.get_many(list(user_terms)[:10])  # cap at 10 to stay fast
            required_embeddings = cache.get_many(required_skills)

            sem_scores = []
            for req_emb in required_embeddings:
                if not req_emb:
                    continue
                best = max(
                    (cosine_similarity(u_emb, req_emb) for u_emb in user_embeddings if u_emb),
                    default=0.0,
                )
                sem_scores.append(best)

            semantic_alignment = float(sum(sem_scores) / len(sem_scores)) if sem_scores else 0.0
        else:
            semantic_alignment = 0.0

        # Blend: 40% exact overlap, 60% semantic alignment
        return min(1.0, 0.4 * overlap_ratio + 0.6 * semantic_alignment)

    def _compute_seniority_alignment(
        self, user_profile: Dict[str, Any], job_analysis: Dict[str, Any]
    ) -> float:
        experience_years = float(user_profile.get("experience_years", 0.0))
        seniority_level  = float(job_analysis.get("seniority_level", 1.0))
        if seniority_level <= 0 or experience_years <= 0:
            return 0.0
        return min(1.0, experience_years / max(1.0, seniority_level))

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))


# ---------------------------------------------------------------------------
# FIX 4: ExplanationAgent — replaces the standalone explain_match() function
#
# WHY: The old function was a loose function with no fallback strategy,
# wrong temperature for JSON output, and manual markdown stripping.
# This class has: correct temperature, Pydantic validation, tiered fallback.
# ---------------------------------------------------------------------------

class ExplanationAgent:
    """
    Generates a human-readable explanation for a match.
    Uses Groq LLaMA. Falls back gracefully if LLM fails.
    """

    _SYSTEM_PROMPT = """You are a concise, practical career advisor.

RULES (follow all of them):
1. Use ONLY the data provided — do not invent skills or tools.
2. Write like a helpful mentor, not a machine. No robotic phrases.
3. Avoid: "matches requirement", "aligns with role", "this skill is relevant".
4. For match_reasons: explain WHY the skill matters in this specific role.
   BAD: "Python matches the role"
   GOOD: "Your Python experience helps you handle the backend scripting this role needs"
5. For missing_skills: expand generic terms slightly but stay within the given inputs.
   e.g. "api" → "building REST APIs with FastAPI or Flask"
6. tip must be specific and actionable based ONLY on the missing skills.
   e.g. "Build a REST API with FastAPI and connect it to a PostgreSQL database"
7. Keep match_reasons to max 3 items, each under 15 words.

Return ONLY valid JSON, no markdown fences:
{
  "match_reasons": ["...", "...", "..."],
  "missing_skills": ["...", "..."],
  "tip": "..."
}"""

    def __init__(self):
        self._client = None  # lazy-init so import errors don't crash startup

    def _get_client(self):
        if self._client is None:
            from groq import Groq
            from app.config import settings
            self._client = Groq(api_key=settings.GROQ_API_KEY)
        return self._client

    def explain(
        self,
        internship_title: str,
        internship_company: str,
        user_skills: str,
        matched_skills: List[str],
        missing_skills: List[str],
        user_experience: str = "",
        user_projects: str = "",
    ) -> Dict[str, Any]:
        """
        Returns a dict with keys: match_reasons, missing_skills, tip.
        Never raises — always returns a valid dict.
        """
        try:
            return self._call_llm(
                internship_title, internship_company,
                user_skills, matched_skills, missing_skills,
                user_experience, user_projects,
            )
        except Exception as exc:
            logger.error("explanation_agent.llm_failed error=%s", exc)
            return self._rule_based_fallback(matched_skills, missing_skills)

    def _call_llm(
        self,
        internship_title: str,
        internship_company: str,
        user_skills: str,
        matched_skills: List[str],
        missing_skills: List[str],
        user_experience: str,
        user_projects: str,
    ) -> Dict[str, Any]:
        client = self._get_client()

        user_message = (
            f"Internship: {internship_title} at {internship_company}\n"
            f"User skills: {user_skills}\n"
            f"User experience: {user_experience}\n"
            f"User projects: {user_projects}\n"
            f"Matched: {', '.join(matched_skills) if matched_skills else 'None'}\n"
            f"Missing: {', '.join(missing_skills) if missing_skills else 'None'}"
        )

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.1,          # FIX: was 0.7 — low temp for stable JSON
            max_tokens=400,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        logger.info("explanation_agent.raw_response length=%d", len(raw))

        # FIX: use Pydantic validation instead of manual JSON parsing
        parsed = self._parse_and_validate(raw)
        return parsed

    def _parse_and_validate(self, raw: str) -> Dict[str, Any]:
        """Parse LLM output safely. Strips fences if model ignores response_format."""
        # Strip markdown fences if present (defensive — shouldn't happen with json_object)
        clean = raw
        if "```" in clean:
            parts = clean.split("```")
            # Take the part after the first fence
            clean = parts[1] if len(parts) > 1 else parts[0]
            if clean.startswith("json"):
                clean = clean[4:]
            clean = clean.strip()

        # Find JSON boundaries
        start, end = clean.find("{"), clean.rfind("}") + 1
        if start != -1 and end > start:
            clean = clean[start:end]

        try:
            data = json.loads(clean)
            # Validate with Pydantic — raises ValidationError if schema is wrong
            validated = ExplanationOutput(**data)
            return {
                "match_reasons": validated.match_reasons[:3],
                "missing_skills": validated.missing_skills[:3],
                "tip": validated.tip,
            }
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("explanation_agent.parse_failed error=%s raw=%s", exc, raw[:200])
            raise  # let explain() catch this and use fallback

    def _rule_based_fallback(
        self, matched_skills: List[str], missing_skills: List[str]
    ) -> Dict[str, Any]:
        """Deterministic fallback when LLM is unavailable."""
        reasons = []
        if matched_skills:
            reasons.append(f"Your {matched_skills[0]} knowledge is directly applicable here")
        if len(matched_skills) > 1:
            reasons.append(f"You already have {len(matched_skills)} of the required skills")
        if not reasons:
            reasons.append("Your profile partially aligns with this role's requirements")

        tip = (
            f"Focus on building experience with {missing_skills[0]} to strengthen this match"
            if missing_skills
            else "Tailor your resume to highlight the skills listed in this internship"
        )

        return {
            "match_reasons": reasons,
            "missing_skills": missing_skills[:3],
            "tip": tip,
        }


# ---------------------------------------------------------------------------
# FIX 5: match_label — derived from score, not hardcoded
# ---------------------------------------------------------------------------

def _derive_match_label(score: float) -> str:
    """
    Generate a match label from the composite score.
    Thresholds are still involved but they drive a label, not a gate.
    """
    if score >= 0.80:
        return "Excellent Match"
    if score >= 0.65:
        return "Strong Match"
    if score >= 0.50:
        return "Good Match"
    if score >= 0.35:
        return "Partial Match"
    return "Low Match"


# ---------------------------------------------------------------------------
# Module-level normalize helper (shared across classes)
# ---------------------------------------------------------------------------

def _normalize(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ""


# ---------------------------------------------------------------------------
# RecommendationEngine — the orchestrator that wires all agents together
# ---------------------------------------------------------------------------

class RecommendationEngine:
    TOP_N = 20

    def __init__(self, db: Session):
        self.db              = db
        self.scoring_agent   = MatchScoringAgent()
        self.job_agent       = JobAnalysisAgent()
        self.explanation_agent = ExplanationAgent()

    def get_recommendations(
        self, user_id: int, limit: int = 20
    ) -> List[InternshipRecommendation]:
        resume = self.db.query(Resume).filter(Resume.user_id == user_id).first()
        if not resume:
            logger.info("recommendation_engine.no_resume user_id=%d", user_id)
            return []

        user_profile = self._build_user_profile(user_id)

        # FIX: build embedding cache once — shared across ALL internship scoring
        embedding_manager = self.scoring_agent.embedding_manager
        cache = EmbeddingCache(embedding_manager)

        # Pre-warm cache with user skill embeddings (computed once, reused 50× below)
        user_skill_texts = [_normalize(s.get("name")) for s in user_profile.get("skills", []) if s.get("name")]
        cache.get_many(user_skill_texts)
        logger.info("recommendation_engine.cache_warmed skills=%d", len(user_skill_texts))

        internships = self._fetch_active_internships()

        # PERF: fetch ALL embedding similarities in ONE query instead of 1-per-internship
        internship_ids = [i.id for i in internships]
        similarity_map = self._fetch_embedding_similarities_batch(user_id, internship_ids)

        results: List[InternshipRecommendation] = []

        for internship in internships:
            required_skills      = self._get_required_skills(internship)
            job_analysis         = self.job_agent.analyze(internship, required_skills)
            embedding_similarity = similarity_map.get(internship.id, 0.0)

            scored = self.scoring_agent.score_match(
                user_profile=user_profile,
                job_analysis=job_analysis,
                embedding_similarity=embedding_similarity,
                cache=cache,   # shared cache passed in
            )

            if scored["composite_score"] <= 0:
                continue

            results.append(
                InternshipRecommendation(
                    internship_id=internship.id,
                    title=internship.title,
                    company=internship.company,
                    location=internship.location,
                    application_url=internship.application_url,
                    similarity_score=scored["signal_breakdown"]["semantic_similarity"],
                    match_percentage=round(scored["composite_score"] * 100, 1),
                    matched_skills=scored["matched_skills"],
                    missing_skills=scored["missing_skills"],
                    match_label=_derive_match_label(scored["composite_score"]),  # FIX: derived
                )
            )

        results.sort(key=lambda r: r.match_percentage, reverse=True)
        results = results[: min(limit, self.TOP_N)]
        self._persist_recommendations(user_id, results)
        return results

    def refresh_for_user(self, user_id: int) -> dict:
        resume = self.db.query(Resume).filter(Resume.user_id == user_id).first()
        if not resume:
            return {"recommendations": 0}

        user_profile = self._build_user_profile(user_id)
        embedding_manager = self.scoring_agent.embedding_manager
        cache = EmbeddingCache(embedding_manager)

        user_skill_texts = [_normalize(s.get("name")) for s in user_profile.get("skills", []) if s.get("name")]
        cache.get_many(user_skill_texts)

        internships = self._fetch_top_internships_for_refresh(user_id)
        self.db.query(Recommendation).filter(Recommendation.user_id == user_id).delete()

        # Batch fetch all similarities upfront
        internship_ids = [i.id for i in internships]
        similarity_map = self._fetch_embedding_similarities_batch(user_id, internship_ids)

        count = 0
        for internship in internships:
            required_skills      = self._get_required_skills(internship)
            job_analysis         = self.job_agent.analyze(internship, required_skills)
            embedding_similarity = similarity_map.get(internship.id, 0.0)

            scored = self.scoring_agent.score_match(
                user_profile=user_profile,
                job_analysis=job_analysis,
                embedding_similarity=embedding_similarity,
                cache=cache,
            )
            if scored["composite_score"] <= 0:
                continue

            self.db.add(
                Recommendation(
                    user_id=user_id,
                    internship_id=internship.id,
                    similarity_score=scored["signal_breakdown"]["semantic_similarity"],
                    match_percentage=round(scored["composite_score"] * 100, 1),
                )
            )
            count += 1

        self.db.commit()
        return {"recommendations": count}

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _fetch_active_internships(self) -> List[Internship]:
        return self.db.query(Internship).filter(Internship.is_active == True).all()

    def _get_required_skills(self, internship: Internship) -> List[str]:
        """Consolidate skills from InternshipSkill table + internship.required_skills field."""
        # Using .all() with scalar column query returns list of single-value tuples in SA 1.x
        # We unpack with [row[0]] pattern to stay compatible with both SA 1.x and 2.x
        rows = (
            self.db.query(InternshipSkill.skill_name)
            .filter(InternshipSkill.internship_id == internship.id)
            .all()
        )
        # Each row is a named tuple like (skill_name,) — extract the value
        from_table = [row[0] for row in rows if row[0]]
        skills = [_normalize(s) for s in from_table if s]

        if internship.required_skills:
            skills.extend(_normalize(s) for s in internship.required_skills if s)

        # Deduplicate while preserving order
        return list(dict.fromkeys(s for s in skills if s))

    def _build_user_profile(self, user_id: int) -> Dict[str, Any]:
        skills      = self.db.query(Skill).filter(Skill.user_id == user_id).all()
        experiences = self.db.query(Experience).filter(Experience.user_id == user_id).all()
        projects    = self.db.query(Project).filter(Project.user_id == user_id).all()

        normalized_skills = [
            {"name": _normalize(s.skill_name), "category": _normalize(s.category)}
            for s in skills if s.skill_name
        ]

        total_months = sum(
            self._estimate_months(e.start_date, e.end_date) for e in experiences
        )

        project_technologies = list({
            _normalize(token)
            for p in projects if p.technologies
            for token in p.technologies.split(",")
            if token.strip()
        })

        return {
            "skills": normalized_skills,
            "experiences": [
                {
                    "role":        _normalize(e.role),
                    "company":     _normalize(e.company),
                    "description": _normalize(e.description),
                    "months":      self._estimate_months(e.start_date, e.end_date),
                }
                for e in experiences
            ],
            "projects": [
                {"name": _normalize(p.name), "description": _normalize(p.description)}
                for p in projects
            ],
            "project_technologies": project_technologies,
            "experience_years":     round(total_months / 12.0, 2),
        }

    def _fetch_embedding_similarities_batch(
        self, user_id: int, internship_ids: List[int]
    ) -> Dict[int, float]:
        """
        Fetch cosine similarities for ALL internships in ONE DB round-trip.

        Old approach: 50 internships = 50 separate SQL queries (~10–12s).
        New approach: 1 query returning all similarities at once (<0.5s).

        Uses string-interpolated IN clause because SQLAlchemy 1.x does not
        support passing a list to ANY(:param) in raw text queries.
        IDs are integers from the DB so interpolation is safe here.
        """
        if not internship_ids:
            return {}

        # Safe: internship_ids are ints fetched directly from DB, not user input
        ids_sql = ",".join(str(i) for i in internship_ids)

        result = self.db.execute(
            text(f"""
                SELECT i.id, 1 - (i.embedding <=> r.embedding) AS similarity
                FROM internships i
                JOIN resumes r ON r.user_id = :user_id
                WHERE i.id IN ({ids_sql})
                  AND i.embedding IS NOT NULL
                  AND r.embedding IS NOT NULL
            """),
            {"user_id": user_id},
        ).fetchall()

        return {row[0]: float(row[1]) for row in result if row[1] is not None}

    def _fetch_embedding_similarity(self, user_id: int, internship_id: int) -> float:
        """Single-internship fetch — kept for use in refresh_for_user."""""
        result = self.db.execute(
            text("""
                SELECT 1 - (i.embedding <=> r.embedding) AS similarity
                FROM internships i
                JOIN resumes r ON r.user_id = :user_id
                WHERE i.id = :internship_id
                  AND i.embedding IS NOT NULL
                  AND r.embedding IS NOT NULL
            """),
            {"user_id": user_id, "internship_id": internship_id},
        ).scalar_one_or_none()

        return float(result) if result is not None else 0.0

    def _estimate_months(
        self, start_date: Optional[date], end_date: Optional[date]
    ) -> int:
        if not start_date:
            return 0
        end = end_date or date.today()
        return max(0, (end.year - start_date.year) * 12 + (end.month - start_date.month))

    def _persist_recommendations(
        self, user_id: int, recommendations: List[InternshipRecommendation]
    ) -> None:
        # SA 1.x compatible: use .query() not select().scalars()
        existing = (
            self.db.query(Recommendation)
            .filter(Recommendation.user_id == user_id)
            .all()
        )
        existing_map = {r.internship_id: r for r in existing}

        for rec in recommendations:
            record = existing_map.get(rec.internship_id)
            if record:
                record.similarity_score = rec.similarity_score
                record.match_percentage = rec.match_percentage
                self.db.add(record)
            else:
                self.db.add(
                    Recommendation(
                        user_id=user_id,
                        internship_id=rec.internship_id,
                        similarity_score=rec.similarity_score,
                        match_percentage=rec.match_percentage,
                    )
                )
        self.db.commit()

    def _fetch_top_internships_for_refresh(self, user_id: int) -> List[Internship]:
        result = self.db.execute(
            text("""
                SELECT i.id
                FROM internships i
                JOIN resumes r ON r.user_id = :user_id
                WHERE i.embedding IS NOT NULL
                  AND r.embedding IS NOT NULL
                  AND i.is_active = true
                ORDER BY i.embedding <=> r.embedding
                LIMIT 50
            """),
            {"user_id": user_id},
        ).fetchall()

        if not result:
            return self._fetch_active_internships()

        internship_ids = [row.id for row in result if row.id is not None]
        return self.db.query(Internship).filter(Internship.id.in_(internship_ids)).all()


# ---------------------------------------------------------------------------
# explain_match() — kept as a module-level function for backward compatibility
# with any router/endpoint that already calls it by name.
# Internally it now delegates to ExplanationAgent.
# ---------------------------------------------------------------------------

_explanation_agent = ExplanationAgent()

def explain_match(
    internship_title: str,
    internship_company: str,
    user_skills: str,
    matched_skills: list,
    missing_skills: list,
    user_experience: str = "",
    user_projects: str = "",
) -> dict:
    """
    Backward-compatible wrapper. Existing callers don't need to change.
    """
    return _explanation_agent.explain(
        internship_title=internship_title,
        internship_company=internship_company,
        user_skills=user_skills,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        user_experience=user_experience,
        user_projects=user_projects,
    )