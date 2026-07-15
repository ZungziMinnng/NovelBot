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
    embedding_model: Mapped[str] = mapped_column(String(100), default="")

    # 自定义 Writer 系统提示词（追加到模板之后）
    writer_system_prompt: Mapped[str] = mapped_column(Text, default="")
    # few-shot 示例轮：[{user, assistant}]，注入为真实消息轮
    writer_examples: Mapped[list] = mapped_column(JSON, default=list)

    # 生成参数（覆盖硬编码默认值）
    enable_critic: Mapped[bool] = mapped_column(Boolean, default=True)
    critic_model: Mapped[str] = mapped_column(String(100), default="")
    enable_detail_review: Mapped[bool] = mapped_column(Boolean, default=False)
    detail_review_model: Mapped[str] = mapped_column(String(100), default="")
    writer_temperature: Mapped[float] = mapped_column(Float, default=0.85)
    # 是否发送自定义温度参数（部分模型不支持 temperature，关闭后从请求中省略）
    writer_use_custom_temperature: Mapped[bool] = mapped_column(Boolean, default=True)
    writer_max_tokens: Mapped[int] = mapped_column(Integer, default=16384)

    # 上下文配置（覆盖硬编码默认值）
    rolling_summary_count: Mapped[int] = mapped_column(Integer, default=8)
    rag_top_k: Mapped[int] = mapped_column(Integer, default=6)
    chat_context_rounds: Mapped[int] = mapped_column(Integer, default=20)  # 0 = 无限
    enable_thinking: Mapped[bool] = mapped_column(Boolean, default=True)
    # DeepSeek 思考档位：off | high | max
    deepseek_thinking_level: Mapped[str] = mapped_column(String(20), default="high")
    # Gemini 思考档位：off | low | medium | high
    gemini_thinking_level: Mapped[str] = mapped_column(String(20), default="medium")
    gemini_stream: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_full_text_context: Mapped[bool] = mapped_column(Boolean, default=False)
    full_text_chapters: Mapped[int] = mapped_column(Integer, default=20)
    context_config: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_chapters: Mapped[int] = mapped_column(Integer, default=0)
    enable_volume_split: Mapped[bool] = mapped_column(Boolean, default=False)
    skip_outline: Mapped[bool] = mapped_column(Boolean, default=False)

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
    world_entities: Mapped[list["WorldEntity"]] = relationship(  # noqa: F821
        "WorldEntity", back_populates="novel", cascade="all, delete-orphan"
    )
    factions: Mapped[list["Faction"]] = relationship(  # noqa: F821
        "Faction", back_populates="novel", cascade="all, delete-orphan"
    )
    locations: Mapped[list["Location"]] = relationship(  # noqa: F821
        "Location", back_populates="novel", cascade="all, delete-orphan"
    )
    notes: Mapped[list["NovelNote"]] = relationship(  # noqa: F821
        "NovelNote", back_populates="novel", cascade="all, delete-orphan"
    )
    glossary_entries: Mapped[list["GlossaryEntry"]] = relationship(  # noqa: F821
        "GlossaryEntry", back_populates="novel", cascade="all, delete-orphan"
    )
    techniques: Mapped[list["Technique"]] = relationship(  # noqa: F821
        "Technique", back_populates="novel", cascade="all, delete-orphan"
    )
    volumes: Mapped[list["Volume"]] = relationship(  # noqa: F821
        "Volume", back_populates="novel", cascade="all, delete-orphan"
    )
    worldview_changes: Mapped[list["WorldviewChange"]] = relationship(  # noqa: F821
        "WorldviewChange", back_populates="novel", cascade="all, delete-orphan"
    )
    world_rules: Mapped[list["WorldRule"]] = relationship(  # noqa: F821
        "WorldRule", back_populates="novel", cascade="all, delete-orphan"
    )
    story_threads: Mapped[list["StoryThread"]] = relationship(  # noqa: F821
        "StoryThread", back_populates="novel", cascade="all, delete-orphan"
    )
