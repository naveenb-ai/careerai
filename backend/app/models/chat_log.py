from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")

    __table_args__ = (
        Index("idx_chat_logs_user_session", "user_id", "session_id"),
        Index("idx_chat_logs_created_at", "created_at"),
    )
