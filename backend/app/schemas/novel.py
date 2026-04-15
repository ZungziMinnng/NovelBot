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
    writer_system_prompt: Optional[str] = None
    enable_critic: Optional[bool] = None
    writer_temperature: Optional[float] = None
    writer_max_tokens: Optional[int] = None


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
    writer_system_prompt: str
    enable_critic: bool
    writer_temperature: float
    writer_max_tokens: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# 新建小说向导 payload
class WizardStep1(BaseModel):
    title: str = ""
    premise: str
    genre: str
    target_length: str = "中篇"
    writing_style: str = "严肃厚重"


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


class WizardFinalize(BaseModel):
    novel_id: int
