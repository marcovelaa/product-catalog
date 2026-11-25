import logging
import os
from typing import Annotated

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import models
import schemas
import telegram_bot
from catalog_assistant import (
    MAX_CATALOG_ITEMS,
    AssistantError,
    AssistantNotConfigured,
    AssistantQuotaExceeded,
    CatalogAssistant,
    CatalogProduct,
    get_catalog_assistant,
)
from database import get_db

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_ORIGIN = "http://localhost:5173"


def parse_allowed_origins(raw: str | None) -> list[str]:
    """Parse a comma-separated origin list; fall back to the local Vite dev server."""
    origins = [origin.strip().rstrip("/") for origin in (raw or "").split(",")]
    origins = [origin for origin in origins if origin]
    return origins or [DEFAULT_ALLOWED_ORIGIN]


# Base.metadata.create_all() is intentionally NOT called: a table auto-created in
# Supabase's `public` schema would skip the Row Level Security set up in
# sql/schema.sql, and Supabase exposes the `public` schema through its Data API.
app = FastAPI(title="Product Catalog API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_allowed_origins(os.getenv("ALLOWED_ORIGINS")),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

DbSession = Annotated[Session, Depends(get_db)]
Assistant = Annotated[CatalogAssistant, Depends(get_catalog_assistant)]
TelegramUpdate = Annotated[
    telegram_bot.TelegramUpdate | None, Depends(telegram_bot.verified_update)
]
TelegramSender = Annotated[
    telegram_bot.TelegramSender, Depends(telegram_bot.get_telegram_sender)
]
TelegramAssistant = Annotated[
    CatalogAssistant, Depends(telegram_bot.get_telegram_assistant)
]

ASSISTANT_UNAVAILABLE = (
    status.HTTP_502_BAD_GATEWAY,
    "Catalog assistant is temporarily unavailable, try again later",
)
# Generic, client-safe details. Provider details are only logged server-side.
ASSISTANT_ERROR_RESPONSES: dict[type[AssistantError], tuple[int, str]] = {
    AssistantNotConfigured: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Catalog assistant is not configured: set GEMINI_API_KEY",
    ),
    AssistantQuotaExceeded: (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Catalog assistant quota exceeded, try again later",
    ),
}


@app.exception_handler(AssistantError)
async def handle_assistant_error(request: Request, exc: AssistantError) -> JSONResponse:
    status_code, detail = ASSISTANT_ERROR_RESPONSES.get(type(exc), ASSISTANT_UNAVAILABLE)
    return JSONResponse(status_code=status_code, content={"detail": detail})


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check for Render; does not touch the database."""
    return {"status": "ok"}


@app.get("/api/v1/products", response_model=list[schemas.ProductResponse])
def list_products(db: DbSession):
    return db.scalars(select(models.Product).order_by(models.Product.id)).all()


@app.post(
    "/api/v1/products",
    response_model=schemas.ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(payload: schemas.ProductCreate, db: DbSession):
    product = models.Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.post(
    "/api/v1/catalog/ask",
    response_model=schemas.CatalogAnswer,
    tags=["Catalog assistant"],
)
def ask_catalog(payload: schemas.CatalogQuestion, db: DbSession, assistant: Assistant):
    """Answer a question using only the first MAX_CATALOG_ITEMS products."""
    products = load_catalog_snapshot(db)
    # The session keeps a pooled connection checked out until its transaction
    # ends. Release it before the slow LLM call so concurrent asks cannot
    # exhaust the pool and stall the product endpoints.
    db.rollback()
    return schemas.CatalogAnswer(answer=assistant.answer(payload.question, products))


TELEGRAM_ACK = {"ok": True}


@app.post("/telegram/webhook", tags=["Telegram bot"])
def telegram_webhook(
    update: TelegramUpdate,
    background_tasks: BackgroundTasks,
    db: DbSession,
    sender: TelegramSender,
    assistant: TelegramAssistant,
) -> dict[str, bool]:
    """Receive a Telegram update and acknowledge it at once.

    Replies are sent from background tasks after the response, because Telegram
    redelivers updates that are not acknowledged quickly and the LLM is slow.
    """
    message = update.message if update else None
    if message is None or message.text is None:
        return TELEGRAM_ACK  # Edited messages, stickers, joins, other update types.
    chat_id = message.chat.id

    interpreted = telegram_bot.interpret_text(message.text)
    if isinstance(interpreted, telegram_bot.Reply):
        background_tasks.add_task(telegram_bot.send_safely, sender, chat_id, interpreted.text)
        return TELEGRAM_ACK

    try:
        products = load_catalog_snapshot(db)
    except SQLAlchemyError as error:
        logger.warning(
            "Catalog query failed for Telegram (chat_id=%s, error=%s)",
            chat_id, type(error).__name__,
        )
        background_tasks.add_task(
            telegram_bot.send_safely, sender, chat_id, telegram_bot.UNAVAILABLE_TEXT
        )
        return TELEGRAM_ACK
    finally:
        # Release the pooled connection before the background LLM call.
        db.rollback()

    background_tasks.add_task(
        telegram_bot.answer_question,
        sender, assistant, chat_id, interpreted.question, products,
    )
    return TELEGRAM_ACK


def load_catalog_snapshot(db: Session) -> list[CatalogProduct]:
    """Read the first MAX_CATALOG_ITEMS products into immutable snapshots."""
    rows = db.execute(
        select(
            models.Product.id,
            models.Product.name,
            models.Product.price,
            models.Product.stock,
        )
        .order_by(models.Product.id)
        .limit(MAX_CATALOG_ITEMS)
    ).all()
    return [
        CatalogProduct(id=row.id, name=row.name, price=float(row.price), stock=row.stock)
        for row in rows
    ]
