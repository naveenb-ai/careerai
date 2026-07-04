from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    internship_id: Mapped[int] = mapped_column(
        ForeignKey("internships.id", ondelete="CASCADE"), index=True, nullable=False
    )
    similarity_score: Mapped[float] = mapped_column(nullable=False)
    match_percentage: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")
    internship = relationship("Internship", back_populates="recommendations")

    __table_args__ = (
        UniqueConstraint("user_id", "internship_id", name="uq_recommendations_user_internship"),
        Index("idx_recommendations_user_id", "user_id"),
        Index("idx_recommendations_score", "similarity_score"),
    )
