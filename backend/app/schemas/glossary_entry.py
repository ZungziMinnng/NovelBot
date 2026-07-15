from pydantic import BaseModel
from datetime import datetime
from typing import Optional

# 分类选项
CATEGORY_OPTIONS = ["描写用词", "人名", "地名", "功法", "丹药", "武器", "常用词", "禁忌词", "自定义"]


class GlossaryCreate(BaseModel):
    novel_id: int
    term: str
    category: str = "自定义"
    forbidden_variants: str = ""
    notes: str = ""
    importance: int = 3


class GlossaryUpdate(BaseModel):
    term: Optional[str] = None
    category: Optional[str] = None
    forbidden_variants: Optional[str] = None
    notes: Optional[str] = None
    importance: Optional[int] = None


class GlossaryOut(BaseModel):
    id: int
    novel_id: int
    term: str
    category: str
    forbidden_variants: str
    notes: str
    importance: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
