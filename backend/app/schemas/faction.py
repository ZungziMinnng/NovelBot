from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class FactionCreate(BaseModel):
    novel_id: int
    name: str
    type: str = ""
    power_level: str = ""
    alignment: str = "中立"
    leader: str = ""
    headquarters: str = ""
    location_id: Optional[int] = None
    member_count: str = ""
    color: str = ""
    description: str = ""
    goals: str = ""
    traits: str = ""
    history: str = ""


class FactionUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    power_level: Optional[str] = None
    alignment: Optional[str] = None
    leader: Optional[str] = None
    headquarters: Optional[str] = None
    location_id: Optional[int] = None
    member_count: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    goals: Optional[str] = None
    traits: Optional[str] = None
    history: Optional[str] = None


class FactionOut(BaseModel):
    id: int
    novel_id: int
    name: str
    type: str
    power_level: str
    alignment: str
    leader: str
    headquarters: str
    location_id: Optional[int]
    member_count: str
    color: str
    description: str
    goals: str
    traits: str
    history: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
