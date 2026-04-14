from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="配角")  # 主角/反派/配角
    age: Mapped[str] = mapped_column(String(20), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    # 完整角色卡（JSON）：性格、动机、弱点、背景、技能
    full_sheet: Mapped[dict] = mapped_column(JSON, default=dict)

    # 当前状态（随章节滚动更新）
    current_state: Mapped[dict] = mapped_column(JSON, default=dict)
    # 格式示例：{"location": "京城", "goal": "...", "relationships": {...}, "known_secrets": [...]}

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="characters")  # noqa: F821
