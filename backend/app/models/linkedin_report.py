from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LinkedInReport(Base):
    __tablename__ = "linkedin_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("linkedin_sessions.session_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    profile_score: Mapped[int] = mapped_column(nullable=False)
    score_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)
    gap_analysis: Mapped[dict] = mapped_column(JSON, nullable=False)
    headline_variants: Mapped[dict] = mapped_column(JSON, nullable=False)
    about_section: Mapped[str | None] = mapped_column(Text)
    experience_improvements: Mapped[dict | None] = mapped_column(JSON)
    skills_optimization: Mapped[dict | None] = mapped_column(JSON)
    improvement_priority: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")

    __table_args__ = (
        Index("idx_linkedin_reports_user_id", "user_id"),
    )
