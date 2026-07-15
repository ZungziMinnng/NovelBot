from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class WriterPresetCreate(BaseModel):
    name: str
    prompt: str = ""
    examples: list[dict] = []


class WriterPresetUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    examples: Optional[list[dict]] = None


class WriterPresetOut(BaseModel):
    id: int
    name: str
    prompt: str
    examples: list[dict]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
