from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoreDraft(BaseModel):
    name: str = ""
    category: str = ""
    level: str = ""
    description: str = ""
    detail: str = ""


class LoreSourceRef(BaseModel):
    origin: Literal["lore", "novel", "rpg", "tavern"]
    kind: Literal["item", "skill", "rule"]
    id: int
    weight: int = Field(50, ge=0, le=100)
    instruction: str = ""


class LoreSourceItem(BaseModel):
    origin: Literal["lore", "novel", "rpg", "tavern"]
    kind: Literal["item", "skill", "rule"]
    id: int
    name: str
    group: str
    brief: str = ""


class LoreFuseIn(BaseModel):
    sources: list[LoreSourceRef] = Field(min_length=1, max_length=8)
    goal: str = ""
    model_ref: str = ""


class LoreEntryCreate(LoreDraft):
    kind: Literal["item", "skill", "rule"]
    name: str
    sources: list[dict] = []


class LoreEntryUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    level: Optional[str] = None
    description: Optional[str] = None
    detail: Optional[str] = None


class LoreEntryOut(LoreDraft):
    id: int
    kind: str
    sources: list[dict] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LoreExportIn(BaseModel):
    target: Literal["novel", "tavern", "rpg"]
    novel_id: Optional[int] = None
    module_id: Optional[int] = None
    card_id: Optional[int] = None


class LoreExportOut(BaseModel):
    target: str
    id: int
