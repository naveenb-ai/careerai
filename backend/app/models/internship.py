"""
app/models/internship.py

Changes from previous version:
- Added `embedding` column using pgvector's Vector(384) type
  → Fixes "Internship has no attribute 'embedding'" in embedding_pipeline.py
  → Allows .filter(Internship.embedding.is_(None)) to work in ORM queries
- Added `skills_extracted` boolean flag for pipeline tracking
"""
from datetime import datetime, date
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, Index, String, Text, func, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Internship(Base):
    __tablename__ = "internships"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    application_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    posted_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    salary_range: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    duplicate_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    required_skills: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # ── pgvector embedding column ─────────────────────────────────────────
    # Vector(384) matches all-MiniLM-L6-v2 output dimension (EMBEDDING_DIM).
    # nullable=True because embedding runs AFTER scraping as a separate step.
    # embedding_pipeline.py uses .filter(Internship.embedding.is_(None))
    # to find rows that still need to be embedded.
    embedding: Mapped[Optional[list]] = mapped_column(Vector(384), nullable=True)

    # ── Pipeline tracking flag ────────────────────────────────────────────
    # Set True by orchestrator after skill extraction completes.
    # Lets you re-run skill extraction independently without re-scraping.
    skills_extracted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    # Relationships (unchanged)
    skills = relationship(
        "InternshipSkill", back_populates="internship", cascade="all, delete-orphan"
    )
    recommendations = relationship(
        "Recommendation", back_populates="internship", cascade="all, delete-orphan"
    )
    applications = relationship(
        "Application", back_populates="internship", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_internships_company",  "company"),
        Index("idx_internships_location", "location"),
        Index("idx_internships_active",   "is_active"),
        Index("idx_internships_source",   "source"),
    )