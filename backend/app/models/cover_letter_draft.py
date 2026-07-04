from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CoverLetterDraft(Base):
    __tablename__ = "cover_letter_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    internship_id: Mapped[int] = mapped_column(ForeignKey("internships.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User")
    internship = relationship("Internship")
    agent_run = relationship("AgentRun")

    __table_args__ = (
        Index("idx_cover_letter_drafts_user_id", "user_id"),
        Index("idx_cover_letter_drafts_status", "status"),
    )
