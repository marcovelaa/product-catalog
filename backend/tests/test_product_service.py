"""Shared product service: the write path used by the bot's admin commands."""

import pytest
from pydantic import ValidationError

import models
import product_service
import schemas
from product_service import ProductChanges


def create(db, **overrides):
    values = {"name": "Mouse", "price": 25.5, "stock": 12, **overrides}
    return product_service.create_product(db, schemas.ProductCreate(**values))


def test_create_product_persists_and_returns_the_row(db_session):
    product = create(db_session, image_url="https://example.com/a.png")

    assert product.id is not None
    assert product.created_at is not None
    stored = db_session.get(models.Product, product.id)
    assert (stored.name, float(stored.price), stored.stock, stored.image_url) == (
        "Mouse", 25.5, 12, "https://example.com/a.png",
    )


def test_create_product_defaults_stock_to_zero_and_image_to_null(db_session):
    product = product_service.create_product(
        db_session, schemas.ProductCreate(name="Mouse", price=1)
    )

    assert (product.stock, product.image_url) == (0, None)


def test_update_product_changes_only_the_given_fields(db_session):
    product = create(db_session, image_url="https://example.com/a.png")

    updated = product_service.update_product(
        db_session, product.id, ProductChanges(price=19.9)
    )

    assert updated.id == product.id
    assert float(updated.price) == 19.9
    assert (updated.name, updated.stock, updated.image_url) == (
        "Mouse", 12, "https://example.com/a.png",
    )


def test_update_product_persists_the_change(db_session):
    product = create(db_session)

    product_service.update_product(
        db_session, product.id, ProductChanges(name="Teclado", stock=0)
    )

    db_session.expire_all()
    stored = db_session.get(models.Product, product.id)
    assert (stored.name, stored.stock) == ("Teclado", 0)


def test_update_product_can_clear_the_image(db_session):
    product = create(db_session, image_url="https://example.com/a.png")

    updated = product_service.update_product(
        db_session, product.id, ProductChanges(image_url=None)
    )

    assert updated.image_url is None
    db_session.expire_all()
    assert db_session.get(models.Product, product.id).image_url is None


def test_update_product_leaves_the_image_alone_when_it_is_not_given(db_session):
    product = create(db_session, image_url="https://example.com/a.png")

    updated = product_service.update_product(db_session, product.id, ProductChanges(stock=3))

    assert updated.image_url == "https://example.com/a.png"


def test_update_product_returns_none_for_a_missing_id(db_session):
    assert product_service.update_product(db_session, 99, ProductChanges(stock=1)) is None


def test_update_product_with_no_changes_returns_the_row_untouched(db_session):
    product = create(db_session)

    updated = product_service.update_product(db_session, product.id, ProductChanges())

    assert (updated.name, float(updated.price), updated.stock) == ("Mouse", 25.5, 12)


@pytest.mark.parametrize(
    "values",
    [
        {"name": None},
        {"price": None},
        {"stock": None},
        {"name": "   "},
        {"name": "x" * 201},
        {"price": -0.01},
        {"price": float("nan")},
        {"price": float("inf")},
        {"stock": -1},
        {"stock": 2_147_483_648},
        {"image_url": "x" * 2049},
        {"color": "red"},
    ],
)
def test_product_changes_enforces_the_same_limits_as_the_api(values):
    with pytest.raises(ValidationError):
        ProductChanges(**values)


def test_product_changes_accepts_the_boundary_values():
    changes = ProductChanges(
        name="x" * 200, price=0, stock=2_147_483_647, image_url="x" * 2048
    )

    assert changes.model_fields_set == {"name", "price", "stock", "image_url"}


def test_product_changes_strips_the_name():
    assert ProductChanges(name="  Mouse  ").name == "Mouse"
