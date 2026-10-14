"""设定库：把道具 / 技能 / 规则混合出的新设定，存成一份中立档案。

与三边都不互相引用：sources 只是留痕，不是活链接，没有任何代码顺着它回写。
"""
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class LoreEntry(Base):
    __tablename__ = "lore_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # item / skill / rule

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 道具类别 / 技能类型；规则不用
    category: Mapped[str] = mapped_column(String(50), default="")
    # 稀有度 / 强度；规则不用
    level: Mapped[str] = mapped_column(String(50), default="")
    # 规则类的正文就放这里
    description: Mapped[str] = mapped_column(Text, default="")
    # 道具 / 技能的使用方式、限制、副作用；规则不用
    detail: Mapped[str] = mapped_column(Text, default="")

    # [{origin, kind, id, name, weight, instruction}]，只记「用过谁」
    sources: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
