from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentState(Base):
    __tablename__ = "agent_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")
