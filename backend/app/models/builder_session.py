from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BuilderSession(Base):
    __tablename__ = "builder_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    current_step: Mapped[int] = mapped_column(default=1, nullable=False)
    resume_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selected_template: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User")

    __table_args__ = (
        Index("idx_builder_sessions_user_id", "user_id"),
    )
