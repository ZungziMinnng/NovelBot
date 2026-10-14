"""熔炉：把酒馆卡 / 小说角色 / 模组 NPC 混合出的新角色，存成一份中立档案。

与三边都不互相引用：sources 只是留痕，不是活链接，没有任何代码顺着它回写。
"""
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ForgeCharacter(Base):
    __tablename__ = "forge_characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    age: Mapped[str] = mapped_column(String(20), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    personality: Mapped[str] = mapped_column(Text, default="")
    speech_style: Mapped[str] = mapped_column(Text, default="")
    appearance: Mapped[str] = mapped_column(Text, default="")
    background: Mapped[str] = mapped_column(Text, default="")
    abilities: Mapped[str] = mapped_column(Text, default="")
    relationships: Mapped[str] = mapped_column(Text, default="")
    # [{"user": ..., "assistant": ...}]
    dialogue_examples: Mapped[list] = mapped_column(JSON, default=list)

    # [{kind, id, name, weight, instruction}]，只记「用过谁」
    sources: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
