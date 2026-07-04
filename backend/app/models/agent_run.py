from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger: Mapped[str] = mapped_column(String(100), nullable=False)
    input_json: Mapped[dict | None] = mapped_column(JSON)
    output_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User")

    __table_args__ = (
        Index("idx_agent_runs_user_id", "user_id"),
        Index("idx_agent_runs_agent_name", "agent_name"),
        Index("idx_agent_runs_status", "status"),
    )
