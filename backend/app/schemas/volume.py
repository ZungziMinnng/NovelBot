from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class VolumeCreate(BaseModel):
    novel_id: int
    number: int
    title: str = ""
    description: str = ""


class VolumeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class VolumeOut(BaseModel):
    id: int
    novel_id: int
    number: int
    title: str
    description: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
