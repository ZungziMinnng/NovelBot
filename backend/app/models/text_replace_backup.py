from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TextReplaceBackup(Base):
    """全书批量替换的原文备份，一次操作一行。

    payload 存每个被改行的完整 before 值，而不是靠反向替换撤销：
    若原文本来就含有 replace_text，反向替换会把那些原有的词一起改掉。
    """

    __tablename__ = "text_replace_backups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)

    find_text: Mapped[str] = mapped_column(String(200), nullable=False)
    replace_text: Mapped[str] = mapped_column(String(200), default="")
    # ["content", "summary", "outline", "memory"]
    scope: Mapped[list] = mapped_column(JSON, default=list)
    # [{"table": "chapters", "row_id": 1, "field": "content", "before": "..."}]
    payload: Mapped[list] = mapped_column(JSON, default=list)

    affected_rows: Mapped[int] = mapped_column(Integer, default=0)
    total_occurrences: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    undone_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)
