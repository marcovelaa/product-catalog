import pytest

import main
import models
from database import get_database_url

PRODUCTS_URL = "/api/v1/products"

VALID_PRODUCT = {
    "name": "Mechanical Keyboard",
    "price": 89.99,
    "stock": 5,
    "image_url": "https://example.com/keyboard.png",
}


def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_products_is_empty_when_there_are_no_products(client):
    response = client.get(PRODUCTS_URL)

    assert response.status_code == 200
    assert response.json() == []


def test_create_product_returns_201_with_generated_fields(client):
    response = client.post(PRODUCTS_URL, json=VALID_PRODUCT)

    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int)
    assert body["created_at"]
    assert body["name"] == VALID_PRODUCT["name"]
    assert body["stock"] == VALID_PRODUCT["stock"]
    assert body["image_url"] == VALID_PRODUCT["image_url"]
    # Price must be a JSON number, never a string like "89.99".
    assert isinstance(body["price"], (int, float))
    assert body["price"] == pytest.approx(VALID_PRODUCT["price"])


def test_create_product_defaults_stock_to_zero_and_image_to_null(client):
    response = client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10})

    assert response.status_code == 201
    body = response.json()
    assert body["stock"] == 0
    assert body["image_url"] is None


def test_created_products_appear_in_the_list_ordered_by_id(client):
    first = client.post(PRODUCTS_URL, json=VALID_PRODUCT).json()
    second = client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10}).json()

    response = client.get(PRODUCTS_URL)

    assert response.status_code == 200
    body = response.json()
    assert [product["id"] for product in body] == [first["id"], second["id"]]
    assert body[0]["name"] == VALID_PRODUCT["name"]
    assert isinstance(body[0]["price"], (int, float))


def test_list_products_tolerates_rows_inserted_outside_the_api(client, db_session):
    # Rows added from the Supabase dashboard skip the API's input validation.
    db_session.add_all(
        [
            models.Product(name="", price=1, stock=0),
            models.Product(name="x" * 300, price=2, stock=1),
        ]
    )
    db_session.commit()

    response = client.get(PRODUCTS_URL)

    assert response.status_code == 200
    assert [product["name"] for product in response.json()] == ["", "x" * 300]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"price": 10}, id="missing-name"),
        pytest.param({"name": "", "price": 10}, id="empty-name"),
        pytest.param({"name": "   ", "price": 10}, id="whitespace-name"),
        pytest.param({"name": "Mouse", "price": -1}, id="negative-price"),
        pytest.param({"name": "Mouse", "price": 10, "stock": -1}, id="negative-stock"),
        # The stock column is a Postgres integer (int32); larger values would fail in the
        # database with a 500 instead of a clean validation error.
        pytest.param({"name": "Mouse", "price": 10, "stock": 2_147_483_648}, id="stock-over-int32"),
        pytest.param({"name": "Mouse", "price": 10, "stock": 99_999_999_999}, id="stock-huge"),
    ],
)
def test_create_product_rejects_invalid_payloads(client, payload):
    response = client.post(PRODUCTS_URL, json=payload)

    assert response.status_code == 422
    assert client.get(PRODUCTS_URL).json() == []


def test_create_product_accepts_the_largest_int32_stock(client):
    response = client.post(PRODUCTS_URL, json={"name": "Bulk", "price": 1, "stock": 2_147_483_647})

    assert response.status_code == 201
    assert response.json()["stock"] == 2_147_483_647


def test_get_database_url_fails_fast_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_database_url()


def test_get_database_url_fails_fast_when_empty(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "   ")

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_database_url()


def test_get_database_url_returns_the_configured_value(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")

    assert get_database_url() == "sqlite://"


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://user:secret@host.example:5432/postgres",
        "postgres://user:secret@host.example:5432/postgres",
    ],
)
def test_get_database_url_pins_psycopg2_for_driverless_postgres_urls(monkeypatch, raw):
    # SQLAlchemy 2.1 maps a bare postgresql:// URL to psycopg 3, which is not
    # installed, so the URL copied from Supabase must be pinned to psycopg2.
    monkeypatch.setenv("DATABASE_URL", raw)

    assert (
        get_database_url()
        == "postgresql+psycopg2://user:secret@host.example:5432/postgres"
    )


def test_get_database_url_keeps_an_explicit_driver(monkeypatch):
    url = "postgresql+psycopg2://user:secret@host.example:5432/postgres"
    monkeypatch.setenv("DATABASE_URL", url)

    assert get_database_url() == url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(None, ["http://localhost:5173"], id="unset-uses-default"),
        pytest.param("", ["http://localhost:5173"], id="empty-uses-default"),
        pytest.param(
            " http://localhost:5173 , https://my-app.vercel.app ,, ",
            ["http://localhost:5173", "https://my-app.vercel.app"],
            id="trims-and-drops-empty-entries",
        ),
        pytest.param(
            "https://my-app.vercel.app/",
            ["https://my-app.vercel.app"],
            id="drops-trailing-slash",
        ),
    ],
)
def test_parse_allowed_origins(raw, expected):
    assert main.parse_allowed_origins(raw) == expected


def test_cors_allows_configured_origin(client):
    response = client.get(PRODUCTS_URL, headers={"Origin": "http://localhost:5173"})

    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_ignores_unknown_origin(client):
    response = client.get(PRODUCTS_URL, headers={"Origin": "https://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers
