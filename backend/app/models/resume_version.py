from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    resume_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    template_name: Mapped[str | None] = mapped_column(String(100))
    ats_score: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="builder")
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    docx_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "version_number"),
        Index("idx_resume_versions_user_id", "user_id"),
    )
