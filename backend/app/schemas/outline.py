from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class OutlineCreate(BaseModel):
    novel_id: int
    start_chapter: int
    end_chapter: int
    volume: int = 1
    title: str = ""
    content: str = ""


class OutlineUpdate(BaseModel):
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None
    title: Optional[str] = None
    content: Optional[str] = None


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
