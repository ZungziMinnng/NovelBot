from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StoryThread(Base):
    """A durable foreshadowing or secret record with explicit lifecycle and provenance."""

    __tablename__ = "story_threads"
    __table_args__ = (
        Index("idx_story_threads_novel_kind_status", "novel_id", "kind", "status"),
        Index("idx_story_threads_novel_due", "novel_id", "due_chapter"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # foreshadowing | secret
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | resolved | abandoned
    source_chapter: Mapped[int] = mapped_column(Integer, default=0)
    due_chapter: Mapped[int] = mapped_column(Integer, default=0)
    resolved_chapter: Mapped[int] = mapped_column(Integer, default=0)
    resolution: Mapped[str] = mapped_column(Text, default="")
    known_by: Mapped[list] = mapped_column(JSON, default=list)
    related_entities: Mapped[list] = mapped_column(JSON, default=list)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="story_threads")  # noqa: F821
