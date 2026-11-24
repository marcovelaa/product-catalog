"""Telegram bot channel for the catalog assistant (Bot API webhook, no polling).

Ports and adapters:
- Port: `TelegramSender`, the only thing the webhook depends on to reply.
- Adapter: `HttpxTelegramSender`, which calls the Bot API `sendMessage` method.

The webhook must acknowledge fast (Telegram redelivers an update that does not
get a 2xx quickly), so every reply, including the slow LLM answer, is sent from
a background task after the HTTP response.
"""

import hmac
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Protocol

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ValidationError

import schemas
from catalog_assistant import (
    AssistantError,
    AssistantNotConfigured,
    AssistantQuotaExceeded,
    CatalogAssistant,
    CatalogItem,
    get_catalog_assistant,
)

logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and a Bot API URL contains the token.
logging.getLogger("httpx").setLevel(logging.WARNING)

SECRET_TOKEN_HEADER = "X-Telegram-Bot-Api-Secret-Token"
TELEGRAM_API_BASE = "https://api.telegram.org"
SEND_TIMEOUT_SECONDS = 10.0
MAX_MESSAGE_LENGTH = 4096  # Bot API limit for sendMessage text.
KNOWN_COMMANDS = frozenset({"start", "help"})

WELCOME_TEXT = (
    "Hi! I am the product catalog assistant.\n\n"
    "Ask me anything about our products, for example:\n"
    "- Do you have keyboards under 100?\n"
    "- Which products are out of stock?\n\n"
    "I answer only from the current catalog. After a while without use the "
    "server sleeps, so the first answer can take about a minute."
)
INVALID_QUESTION_TEXT = "Please send a question between 1 and 500 characters."
BUSY_TEXT = "The assistant is busy right now. Please try again in a minute."
UNAVAILABLE_TEXT = (
    "Sorry, I could not answer right now. Please try again in a minute."
)
NOT_CONFIGURED_TEXT = "The catalog assistant is not set up yet. Please try again later."
ASSISTANT_ERROR_TEXTS: dict[type[AssistantError], str] = {
    AssistantNotConfigured: NOT_CONFIGURED_TEXT,
    AssistantQuotaExceeded: BUSY_TEXT,
}


# --- Update payload (only the fields the bot reads) ----------------------------


class TelegramChat(BaseModel):
    id: int


class TelegramMessage(BaseModel):
    chat: TelegramChat
    text: str | None = None


class TelegramUpdate(BaseModel):
    message: TelegramMessage | None = None


# --- Configuration -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    bot_token: str
    webhook_secret: str

    def __repr__(self) -> str:
        return "TelegramConfig(<redacted>)"


def get_telegram_config() -> TelegramConfig:
    """Read the bot settings; both are optional, so a missing one only disables the bot."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not bot_token or not webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is not configured",
        )
    return TelegramConfig(bot_token=bot_token, webhook_secret=webhook_secret)


Config = Annotated[TelegramConfig, Depends(get_telegram_config)]


async def verified_update(
    request: Request,
    config: Config,
    secret_token: Annotated[str | None, Header(alias=SECRET_TOKEN_HEADER)] = None,
) -> TelegramUpdate | None:
    """Authenticate the request, then parse it. None means "nothing to handle".

    The body is read here, after the secret check, so unauthenticated callers
    learn nothing about the payload format.
    """
    expected = config.webhook_secret.encode()
    if secret_token is None or not hmac.compare_digest(secret_token.encode(), expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        return TelegramUpdate.model_validate(await request.json())
    except (ValueError, ValidationError):
        # Malformed or unexpected payload: acknowledge it so Telegram does not retry.
        return None


# --- Text triage -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reply:
    """A message to send back without calling the assistant."""

    text: str


def interpret_text(text: str) -> Reply | schemas.CatalogQuestion:
    """Map a chat message to a canned reply or a validated catalog question."""
    if text.startswith("/"):
        # "/start", "/help@MyBot", "/start payload"; any command gets the usage text.
        return Reply(WELCOME_TEXT)
    try:
        # Same limits as POST /api/v1/catalog/ask.
        return schemas.CatalogQuestion(question=text)
    except ValidationError:
        return Reply(INVALID_QUESTION_TEXT)


# --- Port and adapter ------------------------------------------------------------


class TelegramSender(Protocol):
    def send_message(self, chat_id: int, text: str) -> None: ...


class TelegramSendError(Exception):
    """The Bot API rejected a message. The message never includes the token."""


class HttpxTelegramSender:
    """TelegramSender backed by the Bot API sendMessage method."""

    def __init__(self, bot_token: str, transport: httpx.BaseTransport | None = None):
        self._url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
        self._transport = transport

    def __repr__(self) -> str:
        return "HttpxTelegramSender(<redacted>)"

    def send_message(self, chat_id: int, text: str) -> None:
        # Plain text (no parse_mode): model output can never break Markdown/HTML parsing.
        payload = {"chat_id": chat_id, "text": text[:MAX_MESSAGE_LENGTH]}
        with httpx.Client(timeout=SEND_TIMEOUT_SECONDS, transport=self._transport) as client:
            response = client.post(self._url, json=payload)
        if response.is_error:
            # Not raise_for_status(): its message would include the URL, and the token.
            raise TelegramSendError(f"Bot API returned HTTP {response.status_code}")


def get_telegram_sender(config: Config) -> TelegramSender:
    return HttpxTelegramSender(config.bot_token)


class _UnconfiguredAssistant:
    """Defers AssistantNotConfigured to answer time so the webhook still acknowledges."""

    def __init__(self, error: AssistantNotConfigured):
        self._error = error

    def answer(self, question: str, products: Sequence[CatalogItem]) -> str:
        raise self._error


def get_telegram_assistant() -> CatalogAssistant:
    try:
        return get_catalog_assistant()
    except AssistantNotConfigured as error:
        return _UnconfiguredAssistant(error)


# --- Background jobs ---------------------------------------------------------------


def send_safely(sender: TelegramSender, chat_id: int, text: str) -> None:
    """Send a message; a failure is logged and swallowed, never raised."""
    try:
        sender.send_message(chat_id, text)
    except Exception as error:
        # Log the class only: httpx error messages can contain the request URL.
        logger.warning(
            "Telegram sendMessage failed (chat_id=%s, error=%s)",
            chat_id, type(error).__name__,
        )


def answer_question(
    sender: TelegramSender,
    assistant: CatalogAssistant,
    chat_id: int,
    question: str,
    products: Sequence[CatalogItem],
) -> None:
    """Ask the assistant and send its answer, or a friendly fallback, to the chat."""
    try:
        text = assistant.answer(question, products)
    except AssistantError as error:
        logger.warning(
            "Catalog assistant failed for Telegram (chat_id=%s, error=%s)",
            chat_id, type(error).__name__,
        )
        text = ASSISTANT_ERROR_TEXTS.get(type(error), UNAVAILABLE_TEXT)
    except Exception as error:
        logger.error(
            "Unexpected catalog assistant failure for Telegram (chat_id=%s, error=%s)",
            chat_id, type(error).__name__,
        )
        text = UNAVAILABLE_TEXT
    send_safely(sender, chat_id, text)
