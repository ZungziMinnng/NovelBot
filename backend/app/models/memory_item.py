from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MemoryItem(Base):
    __tablename__ = "memory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    chapter_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=True)
    chapter_number: Mapped[int] = mapped_column(Integer, default=0)

    # character_state / world_rule / open_loop / reader_promise / timeline
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    field: Mapped[str] = mapped_column(String(100), default="")
    value: Mapped[str] = mapped_column(Text, default="")
    old_value: Mapped[str] = mapped_column(Text, default="")

    # active / outdated / contradicted / resolved / tentative
    status: Mapped[str] = mapped_column(String(30), default="active")
    importance: Mapped[int] = mapped_column(Integer, default=3)
    due_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="memory_items")  # noqa: F821
    chapter: Mapped[Optional["Chapter"]] = relationship("Chapter", back_populates="memory_items")  # noqa: F821

    __table_args__ = (
        Index("idx_memory_items_novel_category_status", "novel_id", "category", "status"),
        Index("idx_memory_items_novel_subject_field", "novel_id", "category", "subject", "field"),
        Index("idx_memory_items_novel_chapter", "novel_id", "chapter_number"),
        Index("idx_memory_items_due", "novel_id", "category", "status", "due_chapter"),
    )
