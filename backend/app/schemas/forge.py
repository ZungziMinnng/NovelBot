from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ForgeExample(BaseModel):
    user: str = ""
    assistant: str = ""


class ForgeSourceRef(BaseModel):
    kind: Literal["tavern", "npc", "novel"]
    id: int
    weight: int = Field(50, ge=0, le=100)
    instruction: str = ""


class ForgeSourceSaved(ForgeSourceRef):
    name: str = ""


class ForgeSourceItem(BaseModel):
    kind: Literal["tavern", "npc", "novel"]
    id: int
    name: str
    group: str
    avatar_url: str = ""
    brief: str = ""


class ForgeFuseIn(BaseModel):
    sources: list[ForgeSourceRef] = Field(min_length=1, max_length=8)
    goal: str = ""
    model_ref: str = ""


class ForgeDraft(BaseModel):
    name: str = ""
    age: str = ""
    description: str = ""
    personality: str = ""
    speech_style: str = ""
    appearance: str = ""
    background: str = ""
    abilities: str = ""
    relationships: str = ""
    dialogue_examples: list[ForgeExample] = []


class ForgeCharacterCreate(ForgeDraft):
    name: str
    sources: list[ForgeSourceSaved] = []


class ForgeCharacterUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[str] = None
    description: Optional[str] = None
    personality: Optional[str] = None
    speech_style: Optional[str] = None
    appearance: Optional[str] = None
    background: Optional[str] = None
    abilities: Optional[str] = None
    relationships: Optional[str] = None
    dialogue_examples: Optional[list[ForgeExample]] = None


class ForgeCharacterOut(ForgeDraft):
    id: int
    sources: list[dict] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ForgeExportIn(BaseModel):
    target: Literal["tavern", "npc", "novel"]
    module_id: Optional[int] = None
    novel_id: Optional[int] = None


class ForgeExportOut(BaseModel):
    target: str
    id: int
