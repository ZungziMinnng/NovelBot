from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class NovelCreate(BaseModel):
    title: str
    genre: str = ""
    premise: str = ""
    writing_style: str = "严肃厚重"
    target_length: str = "中篇"
    core_setting: str = ""
    writer_model: str = ""
    fast_model: str = ""


class NovelUpdate(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    writing_style: Optional[str] = None
    target_length: Optional[str] = None
    core_setting: Optional[str] = None
    book_summary: Optional[str] = None
    writer_model: Optional[str] = None
    fast_model: Optional[str] = None
    embedding_model: Optional[str] = None
    writer_system_prompt: Optional[str] = None
    enable_critic: Optional[bool] = None
    critic_model: Optional[str] = None
    enable_detail_review: Optional[bool] = None
    detail_review_model: Optional[str] = None
    writer_temperature: Optional[float] = None
    writer_max_tokens: Optional[int] = None
    rolling_summary_count: Optional[int] = None
    rag_top_k: Optional[int] = None
    chat_context_rounds: Optional[int] = None
    enable_thinking: Optional[bool] = None
    thinking_level: Optional[str] = None  # "off" | "low" | "medium" | "high"
    gemini_stream: Optional[bool] = None
    enable_full_text_context: Optional[bool] = None
    full_text_chapters: Optional[int] = None
    context_config: Optional[dict] = None


class NovelOut(BaseModel):
    id: int
    title: str
    genre: str
    premise: str
    writing_style: str
    target_length: str
    core_setting: str
    current_volume: int
    current_chapter: int
    book_summary: str
    writer_model: str
    fast_model: str
    embedding_model: str
    writer_system_prompt: str
    enable_critic: bool
    critic_model: str
    enable_detail_review: bool
    detail_review_model: str
    writer_temperature: float
    writer_max_tokens: int
    rolling_summary_count: int
    rag_top_k: int
    chat_context_rounds: int
    enable_thinking: bool
    thinking_level: str
    gemini_stream: bool
    enable_full_text_context: bool
    full_text_chapters: int
    context_config: dict
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
