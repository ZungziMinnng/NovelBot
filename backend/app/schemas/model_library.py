from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ModelEntryCreate(BaseModel):
    display_name: str
    model_id: str
    provider: str = ""
    api_format: str = ""
    model_type: str = "chat"
    provider_id: Optional[int] = None
    context_window: int = Field(default=65536, ge=16384, le=2000000)
    input_price: float = Field(default=0.0, ge=0)
    output_price: float = Field(default=0.0, ge=0)
    price_currency: str = Field(default="CNY", min_length=1, max_length=10)
    currency_to_cny_rate: float = Field(default=1.0, gt=0)


class ModelEntryUpdate(BaseModel):
    display_name: Optional[str] = None
    model_id: Optional[str] = None
    provider: Optional[str] = None
    api_format: Optional[str] = None
    model_type: Optional[str] = None
    provider_id: Optional[int] = None
    context_window: Optional[int] = Field(default=None, ge=16384, le=2000000)
    input_price: Optional[float] = Field(default=None, ge=0)
    output_price: Optional[float] = Field(default=None, ge=0)
    price_currency: Optional[str] = Field(default=None, min_length=1, max_length=10)
    currency_to_cny_rate: Optional[float] = Field(default=None, gt=0)


class ModelEntryOut(BaseModel):
    id: int
    display_name: str
    model_id: str
    provider: str
    api_format: str
    model_type: str
    provider_id: int | None = None
    context_window: int
    input_price: float
    output_price: float
    price_currency: str
    currency_to_cny_rate: float
    created_at: datetime

    model_config = {"from_attributes": True}
