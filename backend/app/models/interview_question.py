from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("interview_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(10))
    skill_tested: Mapped[str | None] = mapped_column(String(100))
    order_index: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_interview_questions_session", "session_id"),
    )
