from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LinkedInSession(Base):
    __tablename__ = "linkedin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    profile_input: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User")

    __table_args__ = (
        Index("idx_linkedin_sessions_user_id", "user_id"),
    )
