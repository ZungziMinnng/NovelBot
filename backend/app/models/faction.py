from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Faction(Base):
    __tablename__ = "factions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(100), default="")
    power_level: Mapped[str] = mapped_column(String(50), default="")
    alignment: Mapped[str] = mapped_column(String(50), default="中立")
    leader: Mapped[str] = mapped_column(String(200), default="")
    headquarters: Mapped[str] = mapped_column(String(500), default="")
    location_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    member_count: Mapped[str] = mapped_column(String(100), default="")
    color: Mapped[str] = mapped_column(String(20), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    goals: Mapped[str] = mapped_column(Text, default="")
    traits: Mapped[str] = mapped_column(Text, default="")
    history: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="factions")  # noqa: F821
