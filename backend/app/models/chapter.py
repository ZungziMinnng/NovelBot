from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, default=1)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    # 章节摘要（确认后 AI 自动生成）
    summary: Mapped[str] = mapped_column(Text, default="")
    # 生成时的用户指令（构思备忘）
    instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    # draft = 草稿, confirmed = 已确认（触发记忆更新）
    status: Mapped[str] = mapped_column(String(20), default="draft")
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="chapters")  # noqa: F821
    memory_items: Mapped[list["MemoryItem"]] = relationship(  # noqa: F821
        "MemoryItem", back_populates="chapter", cascade="all, delete-orphan"
    )
