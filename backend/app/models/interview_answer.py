from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InterviewAnswer(Base):
    __tablename__ = "interview_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(20))
    strengths: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    weaknesses: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    model_answer: Mapped[str | None] = mapped_column(Text)
    improvement_tip: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_interview_answers_session", "session_id"),
        Index("idx_interview_answers_user_id", "user_id"),
    )
