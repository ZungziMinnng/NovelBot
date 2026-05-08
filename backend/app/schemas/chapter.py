from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ChapterCreate(BaseModel):
    novel_id: int
    volume: int = 1
    number: int
    title: str = ""
    content: str = ""


class ChapterUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    volume: Optional[int] = None


class ChapterOut(BaseModel):
    id: int
    novel_id: int
    volume: int
    number: int
    title: str
    content: str
    summary: str
    instruction: Optional[str] = None
    status: str
    word_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChapterConfirmRequest(BaseModel):
    chapter_id: int
