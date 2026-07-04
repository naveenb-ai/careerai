from datetime import datetime
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
