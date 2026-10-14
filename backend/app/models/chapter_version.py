from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ChapterVersion(Base):
    """章节正文的历史版本：每次被覆盖（重新生成/批注重写/全书替换/恢复/手动编辑）之前存一份旧稿。

    chapter_id 不挂外键：删章时由删章路由一并清掉，挂了外键反而要额外处理删除顺序。
    """

    __tablename__ = "chapter_versions"
    __table_args__ = (
        Index("idx_chapter_versions_chapter", "chapter_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # 为什么存这一版：regenerate / rewrite / replace / restore / edit
    reason: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    novel: Mapped["Novel"] = relationship("Novel", back_populates="chapter_versions")  # noqa: F821
