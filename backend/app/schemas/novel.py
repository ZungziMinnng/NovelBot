from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class NovelCreate(BaseModel):
    title: str
    genre: str = ""
    premise: str = ""
    plot_design: str = ""
    writing_style: str = "严肃厚重"
    target_length: str = "中篇"
    core_setting: str = ""
    world_rules_seed: str = ""
    writer_model: str = ""
    fast_model: str = ""
    tags: dict = {}


class NovelUpdate(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    # '' = 按 genre 自动匹配题材卡，'none' = 不用卡，其他 = 指定卡名
    genre_card: Optional[str] = None
    premise: Optional[str] = None
    plot_design: Optional[str] = None
    ending: Optional[str] = None
    protagonist_arc: Optional[str] = None
    writing_style: Optional[str] = None
    target_length: Optional[str] = None
    core_setting: Optional[str] = None
    world_rules_seed: Optional[str] = None
    book_summary: Optional[str] = None
    writer_model: Optional[str] = None
    fast_model: Optional[str] = None
    embedding_model: Optional[str] = None
    writer_system_prompt: Optional[str] = None
    writer_examples: Optional[list[dict]] = None
    enable_critic: Optional[bool] = None
    critic_model: Optional[str] = None
    enable_detail_review: Optional[bool] = None
    detail_review_model: Optional[str] = None
    writer_temperature: Optional[float] = None
    writer_use_custom_temperature: Optional[bool] = None
    writer_max_tokens: Optional[int] = None
    build_temperature: Optional[float] = None
    rolling_summary_count: Optional[int] = Field(default=None, ge=3, le=12)
    rag_top_k: Optional[int] = Field(default=None, ge=0, le=10)
    chat_context_rounds: Optional[int] = None
    enable_thinking: Optional[bool] = None
    deepseek_thinking_level: Optional[str] = None  # "off" | "high" | "max"
    gemini_thinking_level: Optional[str] = None    # "off" | "low" | "medium" | "high"
    gemini_stream: Optional[bool] = None
    enable_full_text_context: Optional[bool] = None
    full_text_chapters: Optional[int] = None
    context_config: Optional[dict] = None
    tags: Optional[dict] = None
    blurb: Optional[str] = None
    submission_tags: Optional[list[str]] = None
    estimated_chapters: Optional[int] = None
    enable_volume_split: Optional[bool] = None
    skip_outline: Optional[bool] = None
    # 启用的规则广场条目。update 走 exclude_none，所以传 None 是"不改"，传 [] 才是"全关"
    enabled_rule_ids: Optional[list[int]] = None


class NovelOut(BaseModel):
    id: int
    title: str
    genre: str
    genre_card: str = ""
    premise: str
    plot_design: str
    ending: str = ""
    protagonist_arc: str = ""
    writing_style: str
    target_length: str
    core_setting: str
    world_rules_seed: str
    current_volume: int
    current_chapter: int
    book_summary: str
    writer_model: str
    fast_model: str
    embedding_model: str
    writer_system_prompt: str
    writer_examples: list[dict]
    enable_critic: bool
    critic_model: str
    enable_detail_review: bool
    detail_review_model: str
    writer_temperature: float
    writer_use_custom_temperature: bool
    writer_max_tokens: int
    build_temperature: float = 0.7
    rolling_summary_count: int
    rag_top_k: int
    chat_context_rounds: int
    enable_thinking: bool
    deepseek_thinking_level: str
    gemini_thinking_level: str
    gemini_stream: bool
    enable_full_text_context: bool
    full_text_chapters: int
    context_config: dict
    tags: dict
    blurb: str
    submission_tags: list[str]
    estimated_chapters: int
    enable_volume_split: bool
    skip_outline: bool
    # None = 从未配置（前端据此预勾选内置规则，不可当成空数组处理）
    enabled_rule_ids: list[int] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# 新建小说向导 payload
class WizardStep2(BaseModel):
    novel_id: int
    raw_world_setting: str
    raw_world_rules: str = ""


class WizardStep3(BaseModel):
    novel_id: int
    characters: list[dict]  # [{name, role, age, description}]


class WizardStep4(BaseModel):
    novel_id: int
    outline_detail: str = "标准"  # 粗略/标准/详细


class WorldOptimizeRequest(BaseModel):
    core_setting: str
    section: Optional[str] = None
