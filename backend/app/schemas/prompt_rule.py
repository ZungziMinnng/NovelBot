from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PromptRuleCreate(BaseModel):
    name: str
    content: str = ""
    category: str = "style"
    enabled: bool = True
    sort_order: int = 0


class PromptRuleUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None


class PromptRuleOut(BaseModel):
    id: int
    name: str
    content: str
    category: str
    enabled: bool
    is_builtin: bool
    builtin_key: str
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
