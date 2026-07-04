from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InterviewReport(Base):
    __tablename__ = "interview_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    internship_id: Mapped[int] = mapped_column(ForeignKey("internships.id"), nullable=False)
    overall_score: Mapped[float] = mapped_column(nullable=False)
    technical_score: Mapped[float] = mapped_column(nullable=False)
    behavioral_score: Mapped[float] = mapped_column(nullable=False)
    readiness_level: Mapped[str] = mapped_column(String(20), nullable=False)
    top_strengths: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    top_improvements: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    recommended_resources: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_interview_reports_user_id", "user_id"),
    )

