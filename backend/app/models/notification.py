from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now() + interval '30 days'"),
        nullable=False,
    )

    user = relationship("User")

    __table_args__ = (
        Index("idx_notifications_user_id", "user_id"),
        Index("idx_notifications_is_read", "user_id", "is_read"),
        Index("idx_notifications_expires", "expires_at"),
    )
