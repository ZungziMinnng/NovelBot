from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class WorldEntityCreate(BaseModel):
    novel_id: int
    type: str  # "item" / "system"
    name: str
    description: str = ""
    function: str = ""
    properties: dict = {}
    current_state: dict = {}
    importance: int = 3


class WorldEntityUpdate(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    function: Optional[str] = None
    properties: Optional[dict] = None
    current_state: Optional[dict] = None
    importance: Optional[int] = None


class WorldEntityOut(BaseModel):
    id: int
    novel_id: int
    type: str
    name: str
    description: str
    function: str
    properties: dict
    current_state: dict
    importance: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
