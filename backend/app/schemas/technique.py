from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class TechniqueCreate(BaseModel):
    novel_id: int
    name: str
    type: str = ""
    description: str = ""
    practitioners: str = ""
    power_level: str = ""
    importance: int = 3


class TechniqueUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    practitioners: Optional[str] = None
    power_level: Optional[str] = None
    importance: Optional[int] = None


class TechniqueOut(BaseModel):
    id: int
    novel_id: int
    name: str
    type: str
    description: str
    practitioners: str
    power_level: str
    importance: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
