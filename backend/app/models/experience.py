from datetime import date
from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Experience(Base):
    __tablename__ = "experiences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
