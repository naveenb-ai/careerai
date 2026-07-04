from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    skill_name: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100))
