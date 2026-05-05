from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(Integer, ForeignKey("novels.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(30), default="city")  # continent/region/city/building/landmark/other
    description: Mapped[str] = mapped_column(Text, default="")

    # 层级：parent_id 指向同一小说的父级区域（如城市所属国家）
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("locations.id"), nullable=True)

    # 静态属性（人口、气候、特征等）
    properties: Mapped[dict] = mapped_column(JSON, default=dict)

    # 动态状态（LLM 每章自动更新：当前态势、控制方等）
    current_state: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel: Mapped["Novel"] = relationship("Novel", back_populates="locations")  # noqa: F821
    children: Mapped[list["Location"]] = relationship(
        "Location", backref="parent", remote_side=[id], lazy="selectin"
    )  # noqa: F821
