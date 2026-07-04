from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Education(Base):
    __tablename__ = "educations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    institution: Mapped[str | None] = mapped_column(String(255))
    degree: Mapped[str | None] = mapped_column(String(255))
    field: Mapped[str | None] = mapped_column(String(255))
    start_year: Mapped[int | None] = mapped_column(Integer)
    end_year: Mapped[int | None] = mapped_column(Integer)
