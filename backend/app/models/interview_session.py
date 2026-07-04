from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    internship_id: Mapped[int] = mapped_column(ForeignKey("internships.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    overall_score: Mapped[float | None] = mapped_column(nullable=True)
    readiness_level: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User")
    internship = relationship("Internship")

    __table_args__ = (
        Index("idx_interview_sessions_user_id", "user_id"),
    )
