from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class VolumeCreate(BaseModel):
    novel_id: int
    number: int
    title: str = ""
    description: str = ""
    endgame_cards: str = ""
    power_tiers: str = ""
    tier_count: int = Field(default=0, ge=0)
    words_per_tier: int = Field(default=0, ge=0)
    spent_payoffs: str = ""


class VolumeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    endgame_cards: Optional[str] = None
    power_tiers: Optional[str] = None
    tier_count: Optional[int] = Field(default=None, ge=0)
    words_per_tier: Optional[int] = Field(default=None, ge=0)
    spent_payoffs: Optional[str] = None


class VolumeOut(BaseModel):
    id: int
    novel_id: int
    number: int
    title: str
    description: str
    endgame_cards: str
    power_tiers: str
    tier_count: int
    words_per_tier: int
    spent_payoffs: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
