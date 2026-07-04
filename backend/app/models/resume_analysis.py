from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    ats_score: Mapped[int] = mapped_column(nullable=False, default=0)
    extracted_skills: Mapped[list[str] | None] = mapped_column(JSON)
    missing_sections: Mapped[list[str] | None] = mapped_column(JSON)
    analysis_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
