from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InternshipSkill(Base):
    __tablename__ = "internship_skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    internship_id: Mapped[int] = mapped_column(
        ForeignKey("internships.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    internship = relationship("Internship", back_populates="skills")

    __table_args__ = (
        Index("idx_internship_skills_internship_id", "internship_id"),
        Index("idx_internship_skills_name", "skill_name"),
    )
