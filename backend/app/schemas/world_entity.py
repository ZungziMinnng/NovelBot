from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class WorldEntityCreate(BaseModel):
    novel_id: int
    type: str  # "item" / "system"
    name: str
    description: str = ""
    properties: dict = {}
    current_state: dict = {}


class WorldEntityUpdate(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    properties: Optional[dict] = None
    current_state: Optional[dict] = None


class WorldEntityOut(BaseModel):
    id: int
    novel_id: int
    type: str
    name: str
    description: str
    properties: dict
    current_state: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
