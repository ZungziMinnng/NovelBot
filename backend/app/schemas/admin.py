from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class MemoryOut(BaseModel):
    id: int
    novel_id: int
    chapter_id: Optional[int] = None
    memory_type: str
    content: str
    volume: int
    chapter_number: int
    in_context: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    in_context: Optional[bool] = None


class OutlineOut(BaseModel):
    id: int
    novel_id: int
    level: str
    volume: int
    chapter_number: int
    title: str
    content: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class OutlineUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
