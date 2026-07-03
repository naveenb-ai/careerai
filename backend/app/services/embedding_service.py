import logging
import numpy as np
from typing import Optional
from sentence_transformers import SentenceTransformer
import torch

logger = logging.getLogger(__name__)

# Model chosen specifically for semantic search and cosine similarity ranking
# Trained on 215M question-answer pairs — perfect for job search matching
MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
BATCH_SIZE = 16  # Safe for 4GB VRAM

# Global model instance — loaded once, reused forever
_model: Optional[SentenceTransformer] = None


def get_model() -> SentenceTransformer:
    """Load model once and cache it in GPU memory."""
    global _model
    if _model is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading {MODEL_NAME} on {device}...")
        _model = SentenceTransformer(MODEL_NAME, device=device)
        logger.info(f"Model loaded! Device: {device}")
    return _model


def embed_text(text: str) -> list[float]:
    """Convert any text into a 384-dimensional vector."""
    if not text or not text.strip():
        return [0.0] * EMBEDDING_DIM
    model = get_model()
    vector = model.encode(
        text,
        normalize_embeddings=True,  # normalizing makes cosine similarity = dot product (faster)
        convert_to_numpy=True
    )
    return vector.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed multiple texts at once using GPU batching.
    Much faster than embedding one by one.
    Used when embedding all internships during scraping.
    """
    if not texts:
        return []
    # Filter empty texts
    texts = [t if t and t.strip() else "internship position" for t in texts]
    model = get_model()
    vectors = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=len(texts) > 50
    )
    return [v.tolist() for v in vectors]


def embed_internship(title: str, company: str, description: str, location: str = "") -> list[float]:
    """
    Create embedding for an internship.
    Title repeated twice to give it more weight — the title is the most
    important signal for matching (a 'Python Developer' should match
    'Python' searches more than a job that just mentions Python once).
    """
    text = f"{title} {title} at {company} in {location}. {description[:500]}"
    return embed_text(text)


def embed_resume(skills: list[str], experience: str = "", summary: str = "") -> list[float]:
    """
    Create embedding for a resume.
    Skills listed twice because they're the strongest matching signal.
    Format mimics a job query so it matches well against job descriptions.
    """
    skills_text = " ".join(skills)
    # Format as if the person is describing themselves for a job
    text = f"Experienced in {skills_text}. Skills: {skills_text}. {summary} {experience[:300]}"
    return embed_text(text)


def embed_query(query: str) -> list[float]:
    """
    Convert a search query into a vector.
    This is called in real-time when user searches.
    With GPU: takes ~5-10ms per query.
    """
    return embed_text(query)


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """
    Calculate similarity between two vectors.
    Since we use normalize_embeddings=True above,
    cosine similarity = simple dot product (faster).
    Returns 0.0 to 1.0
    """
    a = np.array(vec1)
    b = np.array(vec2)
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def normalize_score(raw_score: float, min_val: float = 0.0, max_val: float = 0.45) -> float:
    """
    Normalize raw cosine similarity to a 0-100 display percentage.
    
    Why normalize? all-MiniLM models typically score 0.15-0.45 for
    related but not identical texts. Raw scores look low to users.
    We map this range to 50-100% for display.
    
    Example:
      raw 0.30 → display 83%
      raw 0.20 → display 72%
      raw 0.10 → display 61%
    """
    normalized = (raw_score - min_val) / (max_val - min_val)
    normalized = max(0.0, min(1.0, normalized))
    # Map to 50-100% range (no job shows below 50% — that means completely unrelated)
    display_score = 50 + (normalized * 50)
    return round(display_score, 1)