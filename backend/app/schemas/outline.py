from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class OutlineCreate(BaseModel):
    novel_id: int
    start_chapter: int
    end_chapter: int
    volume: int = 1
    title: str = ""
    content: str = ""
    chapter_role: str = ""
    emotion_tone: str = ""
    emotion_intensity: int = Field(default=0, ge=0, le=5)
    hook_type: str = ""
    hook_strength: int = Field(default=0, ge=0, le=5)


class OutlineUpdate(BaseModel):
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None
    title: Optional[str] = None
    content: Optional[str] = None
    # 计划字段允许写空串清空（"未规划"是有效状态），所以不用 None 表示"不改"以外的含义
    chapter_role: Optional[str] = None
    emotion_tone: Optional[str] = None
    emotion_intensity: Optional[int] = Field(default=None, ge=0, le=5)
    hook_type: Optional[str] = None
    hook_strength: Optional[int] = Field(default=None, ge=0, le=5)


class OutlineOut(BaseModel):
    id: int
    novel_id: int
    level: str
    volume: int
    chapter_number: int
    start_chapter: int
    end_chapter: int
    title: str
    content: str
    chapter_role: str
    emotion_tone: str
    emotion_intensity: int
    hook_type: str
    hook_strength: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
