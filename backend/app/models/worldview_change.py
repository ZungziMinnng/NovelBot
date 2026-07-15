from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class WorldviewChange(Base):
    """世界观变更日志：core_setting 的追加式覆盖层。

    每条记录一个被剧情推翻/更新的设定，带 effective_chapter（第几章起生效）。
    生成第 N 章时注入 status=confirmed 且 effective_chapter<=N 的条目，
    与原世界观冲突时以变更为准——避免覆盖原文档破坏早期章节的时间有效性。
    """
    __tablename__ = "worldview_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes: Mapped[str] = mapped_column(Text, default="")
    effective_chapter: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")  # confirmed | pending
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ai

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    novel: Mapped["Novel"] = relationship("Novel", back_populates="worldview_changes")  # noqa: F821
