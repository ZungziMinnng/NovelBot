from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class WorldEntity(Base):
    __tablename__ = "world_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # "item" / "system"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    # 固有功能（具体能力和作用，手动维护，LLM 每章更新不写入）
    function: Mapped[str] = mapped_column(Text, default="")

    # 静态属性（手动维护，类似角色的 full_sheet）
    properties: Mapped[dict] = mapped_column(JSON, default=dict)

    # 动态状态（LLM 每章自动更新，类似角色的 current_state）
    current_state: Mapped[dict] = mapped_column(JSON, default=dict)

    # 重要性权重（1-5，默认3中性），检索时按 相似度×重要性 重排
    importance: Mapped[int] = mapped_column(Integer, default=3)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="world_entities")  # noqa: F821
