from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class WorldviewChangeCreate(BaseModel):
    novel_id: int
    fact: str
    supersedes: str = ""
    effective_chapter: int = 0
    status: str = "confirmed"
    source: str = "manual"


class WorldviewChangeUpdate(BaseModel):
    fact: Optional[str] = None
    supersedes: Optional[str] = None
    effective_chapter: Optional[int] = None
    status: Optional[str] = None


class WorldviewChangeOut(BaseModel):
    id: int
    novel_id: int
    fact: str
    supersedes: str
    effective_chapter: int
    status: str
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}
