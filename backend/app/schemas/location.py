from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class LocationCreate(BaseModel):
    novel_id: int
    name: str
    type: str = "city"  # continent/region/city/building/landmark/other
    description: str = ""
    parent_id: Optional[int] = None
    properties: dict = {}
    current_state: dict = {}


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = None
    properties: Optional[dict] = None
    current_state: Optional[dict] = None


class LocationOut(BaseModel):
    id: int
    novel_id: int
    name: str
    type: str
    description: str
    parent_id: Optional[int] = None
    properties: dict
    current_state: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
