from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class NoteCreate(BaseModel):
    novel_id: int
    title: str
    content: str = ""
    importance: int = 3


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    importance: Optional[int] = None


class NoteOut(BaseModel):
    id: int
    novel_id: int
    title: str
    content: str
    importance: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
