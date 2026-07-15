from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class WorldRuleCreate(BaseModel):
    novel_id: int
    kind: str  # "rule" | "element"
    title: str = ""
    content: str = ""
    importance: int = 3
    enabled: bool = True


class WorldRuleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    importance: Optional[int] = None
    enabled: Optional[bool] = None


class WorldRuleOut(BaseModel):
    id: int
    novel_id: int
    kind: str
    title: str
    content: str
    importance: int
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
