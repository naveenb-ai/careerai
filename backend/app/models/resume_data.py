from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ResumeData(Base):
    __tablename__ = "resume_data"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    linkedin: Mapped[str | None] = mapped_column(String(255))
    github: Mapped[str | None] = mapped_column(String(255))
    portfolio: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
