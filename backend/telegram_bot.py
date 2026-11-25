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
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Protocol

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import schemas
from catalog_assistant import (
    AssistantError,
    AssistantNotConfigured,
    AssistantQuotaExceeded,
    CatalogAssistant,
    CatalogItem,
    CatalogProduct,
    get_catalog_assistant,
)

logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and a Bot API URL contains the token.
logging.getLogger("httpx").setLevel(logging.WARNING)

SECRET_TOKEN_HEADER = "X-Telegram-Bot-Api-Secret-Token"
TELEGRAM_API_BASE = "https://api.telegram.org"
SEND_TIMEOUT_SECONDS = 10.0
MAX_MESSAGE_LENGTH = 4096  # Bot API limit for sendMessage text.
HELP_COMMANDS = frozenset({"start", "help", "ayuda"})

MAX_RECENT_UPDATES = 1000

# Fixed replies are in Spanish, like the web UI. The assistant's own answers are
# written by the model in the language of the question.
WELCOME_TEXT = (
    "¡Hola! Soy el asistente del catálogo de productos.\n\n"
    "Pregúntame lo que quieras sobre precios y existencias, por ejemplo:\n"
    "- ¿Tienen teclados por menos de 100?\n"
    "- ¿Qué productos están agotados?\n\n"
    "Comandos:\n"
    "/productos - lista los productos con su id, precio y existencias\n"
    "/id - muestra tu ID de usuario de Telegram\n\n"
    "Envía preguntas de 1 a 500 caracteres. Respondo solo con la información "
    "actual del catálogo. Si el servidor lleva un rato sin uso se suspende, así "
    "que la primera respuesta puede tardar cerca de un minuto."
)
ADMIN_HELP_SECTION = (
    "Comandos de administrador:\n"
    "/agregar Nombre; precio; stock; url opcional\n"
    "/editar <id> campo=valor; campo=valor\n"
    "Los campos de /editar son: nombre, precio, stock, imagen. "
    "Separa los valores con punto y coma (;), así el precio puede llevar coma "
    "decimal, por ejemplo 25,50."
)
UNKNOWN_COMMAND_TEXT = (
    "Ese comando no existe o aún no está disponible. "
    "Envía /ayuda para ver los comandos disponibles."
)
NO_PRODUCTS_TEXT = "Todavía no hay productos en el catálogo."
ID_UNAVAILABLE_TEXT = "No puedo ver tu ID de usuario en este mensaje, así que no está disponible."
PRODUCT_LIST_MORE_TEXT = "… y {count} más. Pregunta por uno concreto."
INVALID_QUESTION_TEXT = "Por favor, envía una pregunta de entre 1 y 500 caracteres."
BUSY_TEXT = "El asistente está ocupado en este momento. Inténtalo de nuevo en un minuto."
UNAVAILABLE_TEXT = (
    "Lo siento, no he podido responder ahora mismo. Inténtalo de nuevo en un minuto."
)
NOT_CONFIGURED_TEXT = (
    "El asistente del catálogo aún no está configurado. Inténtalo de nuevo más tarde."
)
ASSISTANT_ERROR_TEXTS: dict[type[AssistantError], str] = {
    AssistantNotConfigured: NOT_CONFIGURED_TEXT,
    AssistantQuotaExceeded: BUSY_TEXT,
}


# --- Update payload (only the fields the bot reads) ----------------------------


class TelegramChat(BaseModel):
    id: int


class TelegramUser(BaseModel):
    id: int


class TelegramMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chat: TelegramChat
    # `from` is a Python keyword. It is absent on channel posts.
    from_user: TelegramUser | None = Field(default=None, alias="from")
    text: str | None = None

    @property
    def sender_id(self) -> int | None:
        """The author's user id; this, never the chat id, identifies an admin."""
        return self.from_user.id if self.from_user else None


class TelegramUpdate(BaseModel):
    update_id: int | None = None
    message: TelegramMessage | None = None


# --- Duplicate deliveries --------------------------------------------------------


class RecentUpdates:
    """Bounded, thread-safe record of recently seen update ids.

    Telegram redelivers an update when the webhook is slow to answer (for
    example during a Render cold start), which would otherwise send the user a
    second reply. Limitation: the record lives in process memory, so it is
    cleared when the service restarts or sleeps (Render free tier). It covers
    the common case, a redelivery within the same process lifetime, not every
    case.
    """

    def __init__(self, max_entries: int = MAX_RECENT_UPDATES):
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._max_entries = max_entries
        self._seen: OrderedDict[int, None] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)

    def first_time(self, update_id: int) -> bool:
        """Record `update_id`; True if it was not already in the record."""
        with self._lock:
            if update_id in self._seen:
                return False
            self._seen[update_id] = None
            if len(self._seen) > self._max_entries:
                self._seen.popitem(last=False)  # evict the oldest id
            return True


_recent_updates = RecentUpdates()


def get_recent_updates() -> RecentUpdates:
    return _recent_updates


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


def parse_admin_ids(raw: str | None) -> frozenset[int]:
    """Parse a comma-separated list of Telegram user ids; junk items are ignored.

    Fails closed: a missing or empty value, or one with no valid id, means nobody
    is an admin. Only plain positive integers count (user ids are positive; a
    group chat id is negative, so it can never be listed by mistake).
    """
    ids: set[int] = set()
    for item in (raw or "").split(","):
        item = item.strip()
        if item.isascii() and item.isdigit() and int(item) > 0:
            ids.add(int(item))
    return frozenset(ids)


def get_telegram_admin_ids() -> frozenset[int]:
    """Sender ids allowed to use admin commands (TELEGRAM_ADMIN_IDS), read per request."""
    return parse_admin_ids(os.getenv("TELEGRAM_ADMIN_IDS"))


def is_admin(sender_id: int | None, admin_ids: frozenset[int]) -> bool:
    """True only for a known sender id on the allow-list."""
    return sender_id is not None and sender_id in admin_ids


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


@dataclass(frozen=True, slots=True)
class ListProducts:
    """The sender asked for the product list (needs a database read)."""


def parse_command(text: str) -> tuple[str, str] | None:
    """Split "/cmd@Bot payload" into ("cmd", "payload"); None if it is not a command.

    The name is lowercased and loses any "@BotName" suffix; the payload is trimmed.
    """
    if not text.startswith("/"):
        return None
    # Split on any whitespace: on a phone the payload often starts on a new line.
    parts = text.split(maxsplit=1)
    head = parts[0]
    payload = parts[1] if len(parts) > 1 else ""
    name = head[1:].partition("@")[0].lower()
    return name, payload.strip()


def help_text(admin: bool) -> str:
    """Usage text; the admin commands are shown to admins only."""
    return f"{WELCOME_TEXT}\n\n{ADMIN_HELP_SECTION}" if admin else WELCOME_TEXT


def interpret_text(
    text: str,
    sender_id: int | None = None,
    admin_ids: frozenset[int] = frozenset(),
) -> Reply | ListProducts | schemas.CatalogQuestion:
    """Map a chat message to a canned reply, a command or a validated catalog question."""
    command = parse_command(text)
    if command is not None:
        name, _payload = command
        if name in HELP_COMMANDS:
            return Reply(help_text(is_admin(sender_id, admin_ids)))
        if name == "id":
            if sender_id is None:
                return Reply(ID_UNAVAILABLE_TEXT)
            return Reply(f"Tu ID de usuario de Telegram es {sender_id}.")
        if name == "productos":
            return ListProducts()
        # Includes /agregar and /editar until they are implemented.
        return Reply(UNKNOWN_COMMAND_TEXT)
    try:
        # Same limits as POST /api/v1/catalog/ask.
        return schemas.CatalogQuestion(question=text)
    except ValidationError:
        return Reply(INVALID_QUESTION_TEXT)


def format_price(price: float) -> str:
    """Two decimals and a decimal comma, like the Spanish UI: 25,50."""
    return f"{price:.2f}".replace(".", ",")


def format_stock(stock: int) -> str:
    return f"{stock} en stock" if stock > 0 else "agotado"


def format_product_list(products: Sequence[CatalogProduct]) -> str:
    """One `#id Name: price · N en stock` line per product, within Telegram's limit."""
    if not products:
        return NO_PRODUCTS_TEXT
    lines = [
        f"#{product.id} {product.name}: {format_price(product.price)} · "
        f"{format_stock(product.stock)}"
        for product in products
    ]
    if len("\n".join(lines)) <= MAX_MESSAGE_LENGTH:
        return "\n".join(lines)
    # Reserve room for the footer, sized for the largest possible count.
    budget = MAX_MESSAGE_LENGTH - len(PRODUCT_LIST_MORE_TEXT.format(count=len(lines))) - 1
    kept: list[str] = []
    used = 0
    for line in lines:
        used += len(line) + (1 if kept else 0)
        if used > budget:
            break
        kept.append(line)
    kept.append(PRODUCT_LIST_MORE_TEXT.format(count=len(lines) - len(kept)))
    return "\n".join(kept)


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
