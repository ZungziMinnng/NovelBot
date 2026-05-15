from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


MemoryCategory = Literal[
    "character_state",
    "world_rule",
    "open_loop",
    "reader_promise",
    "timeline",
]

MemoryStatus = Literal[
    "active",
    "outdated",
    "contradicted",
    "resolved",
    "tentative",
]


class MemoryItemCreate(BaseModel):
    novel_id: int
    chapter_id: Optional[int] = None
    chapter_number: int = 0
    category: MemoryCategory
    subject: str
    field: str = ""
    value: str = ""
    old_value: str = ""
    status: MemoryStatus = "active"
    importance: int = Field(default=3, ge=1, le=5)
    due_chapter: Optional[int] = None
    evidence: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class MemoryItemUpdate(BaseModel):
    chapter_id: Optional[int] = None
    chapter_number: Optional[int] = None
    category: Optional[MemoryCategory] = None
    subject: Optional[str] = None
    field: Optional[str] = None
    value: Optional[str] = None
    old_value: Optional[str] = None
    status: Optional[MemoryStatus] = None
    importance: Optional[int] = Field(default=None, ge=1, le=5)
    due_chapter: Optional[int] = None
    evidence: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


class MemoryItemOut(BaseModel):
    id: int
    novel_id: int
    chapter_id: Optional[int]
    chapter_number: int
    category: str
    subject: str
    field: str
    value: str
    old_value: str
    status: str
    importance: int
    due_chapter: Optional[int]
    evidence: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
