"""
app/scraper/utils/extractor.py

3-layer skill extraction system:
  Layer 1: Rule-based keyword matching against 200+ skill dictionary (fast, free)
  Layer 2: Alias normalization ("JS" → "JavaScript", "k8s" → "Kubernetes")
  Layer 3: LLM via Groq ONLY when < 3 skills found (last resort, not default)

Returns: {"skills": List[str], "confidence": float}
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical skill dictionary — 200+ skills, lowercase keys
# Add more here as you encounter them in job descriptions
# ---------------------------------------------------------------------------
SKILLS_DICTIONARY: set[str] = {
    # Languages
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust",
    "swift", "kotlin", "ruby", "php", "scala", "r", "matlab", "perl",
    "bash", "shell", "powershell",

    # Web Frontend
    "react", "vue", "angular", "next.js", "nuxt", "svelte", "html", "css",
    "sass", "tailwind", "bootstrap", "webpack", "vite", "jquery",

    # Web Backend
    "node.js", "express", "fastapi", "django", "flask", "spring", "spring boot",
    "rails", "laravel", "asp.net", "graphql", "rest api", "websocket",

    # Databases
    "postgresql", "mysql", "sqlite", "mongodb", "redis", "elasticsearch",
    "cassandra", "dynamodb", "firebase", "supabase", "oracle", "sql server",
    "influxdb", "neo4j",

    # Cloud & DevOps
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible",
    "jenkins", "github actions", "ci/cd", "linux", "nginx", "apache",
    "cloudflare", "heroku", "vercel", "railway",

    # Data & ML
    "machine learning", "deep learning", "nlp", "computer vision",
    "data science", "data analysis", "pandas", "numpy", "scikit-learn",
    "tensorflow", "pytorch", "keras", "hugging face", "langchain",
    "matplotlib", "seaborn", "plotly", "tableau", "power bi",
    "apache spark", "hadoop", "airflow", "dbt", "etl",

    # Mobile
    "android", "ios", "flutter", "react native", "swift", "kotlin",
    "xamarin", "ionic",

    # Tools & Practices
    "git", "github", "gitlab", "jira", "confluence", "figma", "postman",
    "swagger", "agile", "scrum", "kanban", "tdd", "microservices",
    "api design", "system design",

    # General Tech
    "excel", "word", "powerpoint", "google sheets", "notion",
    "object oriented programming", "oop", "functional programming",
    "data structures", "algorithms",

    # Soft / Domain skills worth extracting
    "communication", "teamwork", "problem solving", "leadership",
}

# ---------------------------------------------------------------------------
# Alias map — non-canonical → canonical
# Key: what appears in job descriptions
# Value: what we store in the DB
# ---------------------------------------------------------------------------
SKILL_ALIASES: dict[str, str] = {
    # Language aliases
    "js":           "javascript",
    "ts":           "typescript",
    "py":           "python",
    "c plus plus":  "c++",
    "golang":       "go",
    "node":         "node.js",
    "nodejs":       "node.js",
    "reactjs":      "react",
    "react.js":     "react",
    "vuejs":        "vue",
    "vue.js":       "vue",
    "angularjs":    "angular",
    "nextjs":       "next.js",

    # ML aliases
    "ml":           "machine learning",
    "dl":           "deep learning",
    "ai":           "machine learning",  # broad but useful
    "natural language processing": "nlp",
    "cv":           "computer vision",
    "hf":           "hugging face",

    # DB aliases
    "postgres":     "postgresql",
    "mongo":        "mongodb",
    "es":           "elasticsearch",
    "dynamo":       "dynamodb",
    "mssql":        "sql server",

    # Cloud aliases
    "amazon web services": "aws",
    "google cloud": "gcp",
    "gcp":          "gcp",
    "k8s":          "kubernetes",
    "kube":         "kubernetes",
    "tf":           "terraform",

    # Framework aliases
    "fastapi":      "fastapi",
    "spring boot":  "spring boot",
    "springboot":   "spring boot",
    "sklearn":      "scikit-learn",
    "sk-learn":     "scikit-learn",
    "pytorch":      "pytorch",
    "torch":        "pytorch",

    # Tool aliases
    "gh":           "github",
    "gh actions":   "github actions",
    "ci cd":        "ci/cd",
    "rest":         "rest api",
    "restful":      "rest api",
    "restful api":  "rest api",
    "oop":          "object oriented programming",

    # Soft skills
    "communication skills": "communication",
    "team player":          "teamwork",
    "problem-solving":      "problem solving",
}

# Pre-compile regex patterns for each skill (word boundary match)
# Done once at module load, not per extraction call
_SKILL_PATTERNS: dict[str, re.Pattern] = {
    skill: re.compile(r"\b" + re.escape(skill) + r"\b", re.IGNORECASE)
    for skill in SKILLS_DICTIONARY
}
_ALIAS_PATTERNS: dict[str, re.Pattern] = {
    alias: re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
    for alias in SKILL_ALIASES
}


class SkillExtractor:
    """
    3-layer skill extraction.

    Usage:
        extractor = SkillExtractor()
        result = extractor.extract("We need Python, React, and Docker experience...")
        # {"skills": ["docker", "python", "react"], "confidence": 0.9, "layer_used": 1}
    """

    def __init__(self, groq_api_key: Optional[str] = None):
        self._groq_key = groq_api_key
        self._groq_client = None  # lazy init

    # Non-tech job signals — if title/description matches these,
    # skip LLM entirely (sales/marketing/HR jobs never have tech skills)
    _NON_TECH_SIGNALS = {
        "sales", "marketing", "social media", "business development",
        "campus ambassador", "outreach", "telecalling", "hr internship",
        "human resources", "content creator", "graphic design", "video editor",
        "3d animator", "campus coordinator", "campus recruitment",
        "brand marketing", "lead generation", "seo internship",
    }

    def extract(self, text: str, title: str = "") -> dict:
        """
        Main extraction entry point.
        Returns dict with: skills, confidence, layer_used
        """
        if not text and not title:
            return {"skills": [], "confidence": 0.0, "layer_used": 0}

        combined = f"{title} {text}".strip()

        # Layer 1: Rule-based (always runs)
        skills = self._layer1_rule_based(combined)

        # Layer 2: Alias normalization (always runs, adds more from aliases)
        alias_skills = self._layer2_alias_match(combined)
        skills = list(dict.fromkeys(skills + alias_skills))  # merge, preserve order, dedupe

        if len(skills) >= 2:
            return {
                "skills": sorted(skills),
                "confidence": 0.9,
                "layer_used": 1,
            }

        # Skip LLM for non-tech jobs — they will never have extractable
        # tech skills and calling Groq wastes API quota + hits rate limits.
        # These jobs still get stored and embedded — just with fewer skills.
        title_lower = title.strip().lower()
        if any(signal in title_lower for signal in self._NON_TECH_SIGNALS):
            logger.debug(
                "skill_extractor.skip_llm_non_tech title=%s", title[:50]
            )
            return {
                "skills": sorted(skills),
                "confidence": 0.4,
                "layer_used": 1,
            }

        # Also skip LLM if title is empty — nothing useful to send
        if not title.strip():
            return {
                "skills": sorted(skills),
                "confidence": 0.3,
                "layer_used": 1,
            }

        # Layer 3: LLM fallback (only when rule-based found < 3 AND job looks tech)
        logger.info(
            "skill_extractor.using_llm title=%s rule_based_count=%d",
            title[:50], len(skills)
        )
        import time
        time.sleep(2.5)  # 2.5s delay = max ~24 LLM calls/min, safely under Groq free tier limit
        llm_skills = self._layer3_llm_fallback(title, text[:600])
        if llm_skills:
            merged = list(dict.fromkeys(skills + llm_skills))
            return {
                "skills": sorted(merged),
                "confidence": 0.7,
                "layer_used": 3,
            }

        # Return whatever we have even if < 3
        return {
            "skills": sorted(skills),
            "confidence": 0.5 if skills else 0.0,
            "layer_used": 1,
        }

    def _layer1_rule_based(self, text: str) -> list[str]:
        """Match text against pre-compiled skill patterns."""
        found = []
        for skill, pattern in _SKILL_PATTERNS.items():
            if pattern.search(text):
                found.append(skill)
        return found

    def _layer2_alias_match(self, text: str) -> list[str]:
        """Match aliases and return their canonical form."""
        found = []
        for alias, canonical in SKILL_ALIASES.items():
            pattern = _ALIAS_PATTERNS.get(alias)
            if pattern and pattern.search(text):
                found.append(canonical)
        return found

    def _layer3_llm_fallback(self, title: str, description: str) -> list[str]:
        """
        Call Groq to extract skills when rule-based finds < 3.
        Only called for jobs with unusual/vague descriptions.
        Cost: ~$0.0001 per call. At 100 calls/day = $0.01/day.
        """
        try:
            client = self._get_groq_client()
            if not client:
                return []

            prompt = f"""Extract technical skills from this job posting. Return ONLY a JSON array of skill strings, nothing else.

Job title: {title}
Description: {description}

Rules:
- Only extract concrete technical skills (languages, frameworks, tools, platforms)
- Normalize to canonical names (e.g. "JS" → "JavaScript")  
- Maximum 10 skills
- Return: ["skill1", "skill2", ...]"""

            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,   # deterministic for structured output
                max_tokens=150,
            )

            import json
            raw = response.choices[0].message.content.strip()
            # Strip markdown fences if present
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            # Find array boundaries
            start, end = raw.find("["), raw.rfind("]") + 1
            if start != -1 and end > start:
                skills = json.loads(raw[start:end])
                # Normalize and validate
                return [
                    s.strip().lower()
                    for s in skills
                    if isinstance(s, str) and s.strip()
                ][:10]

        except Exception as exc:
            logger.warning("skill_extractor.llm_failed error=%s", exc)

        return []

    def _get_groq_client(self):
        """Lazy-init Groq client."""
        if self._groq_client is None and self._groq_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=self._groq_key)
            except Exception as exc:
                logger.error("skill_extractor.groq_init_failed error=%s", exc)
        return self._groq_client


# ---------------------------------------------------------------------------
# Backward-compatible alias — old code imports DescriptionExtractor
# ---------------------------------------------------------------------------
class DescriptionExtractor:
    """Backward-compatible wrapper. New code should use SkillExtractor directly."""

    def __init__(self) -> None:
        self._extractor = SkillExtractor()

    def extract_skills(self, description: str) -> list[str]:
        result = self._extractor.extract(description)
        return result["skills"]