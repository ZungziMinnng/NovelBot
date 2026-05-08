from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    chapter_id: Mapped[int] = mapped_column(Integer, ForeignKey("chapters.id"), nullable=True)

    # scene_summary / chapter_summary / volume_summary / world_event
    memory_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 对应卷号和章节号（方便按层级查询）
    volume: Mapped[int] = mapped_column(Integer, default=1)
    chapter_number: Mapped[int] = mapped_column(Integer, default=0)

    # ChromaDB 中的 embedding ID（方便关联）
    embedding_id: Mapped[str] = mapped_column(String(100), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    novel: Mapped["Novel"] = relationship("Novel", back_populates="memories")  # noqa: F821


class Outline(Base):
    __tablename__ = "outlines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)

    # book / volume / chapter
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    chapter_number: Mapped[int] = mapped_column(Integer, default=0)
    start_chapter: Mapped[int] = mapped_column(Integer, default=0)
    end_chapter: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="outlines")  # noqa: F821
