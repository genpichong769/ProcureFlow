from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class RequestItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product_id: int = Field(gt=0, strict=True)
    quantity: int = Field(gt=0, le=1000000, strict=True)
    max_unit_price: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class OrderItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product_id: int = Field(gt=0, strict=True)
    quote_id: int = Field(gt=0, strict=True)
    quantity: int = Field(gt=0, le=1000000, strict=True)


class RequestInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requester_id: int = Field(gt=0, strict=True)
    department_id: int = Field(gt=0, strict=True)
    required_delivery_date: date
    reason: str = Field(min_length=1, max_length=1000)
    items: list[RequestItem] = Field(min_length=1, max_length=100)
