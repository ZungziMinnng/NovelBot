from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class WriterPresetCreate(BaseModel):
    name: str
    prompt: str = ""


class WriterPresetUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None


class WriterPresetOut(BaseModel):
    id: int
    name: str
    prompt: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
