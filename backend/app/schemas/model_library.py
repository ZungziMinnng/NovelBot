from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ModelEntryCreate(BaseModel):
    display_name: str
    model_id: str
    provider: str = ""
    api_format: str = ""
    model_type: str = "chat"
    provider_id: Optional[int] = None


class ModelEntryUpdate(BaseModel):
    display_name: Optional[str] = None
    model_id: Optional[str] = None
    provider: Optional[str] = None
    api_format: Optional[str] = None
    model_type: Optional[str] = None
    provider_id: Optional[int] = None


class ModelEntryOut(BaseModel):
    id: int
    display_name: str
    model_id: str
    provider: str
    api_format: str
    model_type: str
    provider_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
