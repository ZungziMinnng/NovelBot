from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class CharacterCreate(BaseModel):
    novel_id: int
    name: str
    role: str = "配角"
    age: str = ""
    description: str = ""
    avatar_url: str = ""
    full_sheet: dict = {}
    current_state: dict = {}


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    age: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    full_sheet: Optional[dict] = None
    current_state: Optional[dict] = None


class EnhanceRequest(BaseModel):
    prompt: str
    scope: list[str] = []


class CharacterOut(BaseModel):
    id: int
    novel_id: int
    name: str
    role: str
    age: str
    description: str
    avatar_url: str
    full_sheet: dict
    current_state: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
