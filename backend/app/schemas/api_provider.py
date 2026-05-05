from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ApiProviderCreate(BaseModel):
    name: str
    base_url: str = ""
    api_key: str = ""
    api_format: str = "openai"


class ApiProviderUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_format: Optional[str] = None


class ApiProviderOut(BaseModel):
    id: int
    name: str
    base_url: str
    api_key_set: bool
    api_key_masked: str
    api_format: str
    created_at: datetime

    model_config = {"from_attributes": True}
