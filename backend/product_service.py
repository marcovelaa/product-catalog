"""Product writes shared by every caller that is allowed to change the catalog.

Authorization is the caller's job: the public REST API only creates products,
and the Telegram bot calls `update_product` only after its admin check. There is
deliberately no public route that edits a product.

Both functions commit; on a database error the caller must roll back.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

import models
import schemas


class ProductChanges(BaseModel):
    """A partial update: only the fields that were set are changed.

    Same limits as `schemas.ProductBase`. `image_url=None` is a real change (it
    clears the image), so "not given" is told apart through `model_fields_set`.
    """

    model_config = ConfigDict(extra="forbid")

    name: schemas.ProductName | None = None
    price: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    stock: Annotated[int, Field(ge=0, le=2_147_483_647)] | None = None
    image_url: Annotated[str, Field(max_length=2048)] | None = None

    @model_validator(mode="after")
    def reject_null_for_required_columns(self) -> "ProductChanges":
        for field in ("name", "price", "stock"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


def create_product(db: Session, data: schemas.ProductCreate) -> models.Product:
    """Insert a product and return it, refreshed from the database."""
    product = models.Product(**data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def update_product(
    db: Session, product_id: int, changes: ProductChanges
) -> models.Product | None:
    """Apply `changes` to a product; None if there is no product with that id."""
    product = db.get(models.Product, product_id)
    if product is None:
        return None
    for field, value in changes.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product
