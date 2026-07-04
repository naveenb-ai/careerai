from datetime import datetime, date
from sqlalchemy import Date, DateTime, ForeignKey, Float, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SkillSnapshot(Base):
    __tablename__ = "skill_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    frequency_pct: Mapped[float] = mapped_column(Float, nullable=False)
    trend: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")

    __table_args__ = (
        Index("idx_skill_snapshots_user_id", "user_id"),
        Index("idx_skill_snapshots_date", "snapshot_date"),
    )
