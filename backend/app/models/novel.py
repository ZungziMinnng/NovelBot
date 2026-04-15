from datetime import datetime
from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Novel(Base):
    __tablename__ = "novels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    genre: Mapped[str] = mapped_column(String(50), default="")
    premise: Mapped[str] = mapped_column(Text, default="")
    writing_style: Mapped[str] = mapped_column(String(50), default="严肃厚重")
    target_length: Mapped[str] = mapped_column(String(20), default="中篇")

    # 核心设定文档（世界观 AI 扩写后）
    core_setting: Mapped[str] = mapped_column(Text, default="")
    # 当前写作进度：卷号/章节号
    current_volume: Mapped[int] = mapped_column(Integer, default=1)
    current_chapter: Mapped[int] = mapped_column(Integer, default=0)
    # 全书摘要
    book_summary: Mapped[str] = mapped_column(Text, default="")

    # 模型配置（覆盖全局默认）
    writer_model: Mapped[str] = mapped_column(String(100), default="")
    fast_model: Mapped[str] = mapped_column(String(100), default="")

    # 自定义 Writer 系统提示词（追加到模板之后）
    writer_system_prompt: Mapped[str] = mapped_column(Text, default="")

    # 生成参数（覆盖硬编码默认值）
    enable_critic: Mapped[bool] = mapped_column(Boolean, default=True)
    writer_temperature: Mapped[float] = mapped_column(Float, default=0.85)
    writer_max_tokens: Mapped[int] = mapped_column(Integer, default=4096)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    chapters: Mapped[list["Chapter"]] = relationship(  # noqa: F821
        "Chapter", back_populates="novel", cascade="all, delete-orphan"
    )
    characters: Mapped[list["Character"]] = relationship(  # noqa: F821
        "Character", back_populates="novel", cascade="all, delete-orphan"
    )
    memories: Mapped[list["Memory"]] = relationship(  # noqa: F821
        "Memory", back_populates="novel", cascade="all, delete-orphan"
    )
    outlines: Mapped[list["Outline"]] = relationship(  # noqa: F821
        "Outline", back_populates="novel", cascade="all, delete-orphan"
    )
