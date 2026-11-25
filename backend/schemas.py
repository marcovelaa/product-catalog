from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ProductName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
QuestionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class ProductBase(BaseModel):
    """Input rules for products submitted through the API."""

    name: ProductName
    # float (not Decimal) so the price is serialized as a JSON number.
    price: float = Field(ge=0, allow_inf_nan=False)
    # Upper bound = the largest Postgres `integer` (the column type in sql/schema.sql).
    stock: int = Field(default=0, ge=0, le=2_147_483_647)
    image_url: str | None = Field(default=None, max_length=2048)


class ProductCreate(ProductBase):
    pass


class ProductResponse(BaseModel):
    """Output shape. It has no input constraints on purpose: rows inserted from
    the Supabase dashboard skip API validation and must still be listable."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    price: float
    stock: int
    image_url: str | None = None
    created_at: datetime


class CatalogQuestion(BaseModel):
    question: QuestionText


class CatalogAnswer(BaseModel):
    answer: str
