from datetime import datetime
from typing import Optional
from sqlalchemy import Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AuthorNote(Base):
    """作者自己的便签/章节备注。

    和 NovelNote（设定笔记）不同：这里的内容只给作者看，不进向量库、不进任何提示词。
    chapter_number = 写到第几章时提醒我；按章号存，那一章还没写也能先挂上。
    调整章节顺序/插章时由 chapter_order 跟着换号。空 = 不挂章的灵感便签。
    """

    __tablename__ = "author_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    chapter_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    content: Mapped[str] = mapped_column(Text, default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="author_notes")  # noqa: F821
