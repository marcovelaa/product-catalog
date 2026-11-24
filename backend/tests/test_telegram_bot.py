"""Telegram webhook tests. They never reach the network: the Bot API sender and
the catalog assistant are always faked (or use httpx.MockTransport)."""

import json
import logging

import httpx
import pytest
from sqlalchemy.exc import OperationalError

import telegram_bot
from catalog_assistant import AssistantQuotaExceeded, AssistantUnavailable
from database import get_db
from main import app
from telegram_bot import (
    MAX_MESSAGE_LENGTH,
    SECRET_TOKEN_HEADER,
    HttpxTelegramSender,
    TelegramSendError,
    get_telegram_assistant,
    get_telegram_sender,
)

WEBHOOK_URL = "/telegram/webhook"
PRODUCTS_URL = "/api/v1/products"
BOT_TOKEN = "123456789:TEST-bot-token"
WEBHOOK_SECRET = "test-secret_123"
CHAT_ID = 4242


# --- Fakes and helpers -------------------------------------------------------


class FakeSender:
    """In-memory TelegramSender that records every message."""

    def __init__(self, error=None):
        self._error = error
        self.sent = []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        if self._error is not None:
            raise self._error


class FakeAssistant:
    def __init__(self, answer="We have 5 keyboards in stock.", error=None):
        self._answer = answer
        self._error = error
        self.calls = []

    def answer(self, question, products):
        self.calls.append({"question": question, "products": list(products)})
        if self._error is not None:
            raise self._error
        return self._answer


def text_update(text, chat_id=CHAT_ID):
    return {
        "update_id": 1001,
        "message": {
            "message_id": 7,
            "date": 1_700_000_000,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "Ana"},
            "text": text,
        },
    }


def post_update(client, update, secret=WEBHOOK_SECRET):
    headers = {} if secret is None else {SECRET_TOKEN_HEADER: secret}
    return client.post(WEBHOOK_URL, json=update, headers=headers)


@pytest.fixture
def telegram_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)


@pytest.fixture
def use_sender():
    def install(sender):
        app.dependency_overrides[get_telegram_sender] = lambda: sender
        return sender

    yield install
    app.dependency_overrides.pop(get_telegram_sender, None)


@pytest.fixture
def sender(telegram_env, use_sender):
    return use_sender(FakeSender())


@pytest.fixture
def use_assistant():
    def install(assistant):
        app.dependency_overrides[get_telegram_assistant] = lambda: assistant
        return assistant

    yield install
    app.dependency_overrides.pop(get_telegram_assistant, None)


@pytest.fixture
def assistant(use_assistant):
    return use_assistant(FakeAssistant())


# --- Security and configuration ----------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="empty"),
        pytest.param("wrong-secret", id="wrong"),
        pytest.param(WEBHOOK_SECRET + "x", id="longer"),
    ],
)
def test_webhook_rejects_a_missing_or_wrong_secret(client, sender, assistant, secret):
    response = post_update(client, text_update("Do you have keyboards?"), secret=secret)

    assert response.status_code == 401
    assert WEBHOOK_SECRET not in response.text
    assert sender.sent == []
    assert assistant.calls == []


@pytest.mark.parametrize(
    ("token", "secret"),
    [
        pytest.param("", "", id="nothing"),
        pytest.param(BOT_TOKEN, "", id="no-secret"),
        pytest.param("", WEBHOOK_SECRET, id="no-token"),
        pytest.param("   ", WEBHOOK_SECRET, id="blank-token"),
    ],
)
def test_webhook_returns_503_when_the_bot_is_not_configured(
    client, monkeypatch, use_sender, assistant, token, secret
):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", secret)
    fake = use_sender(FakeSender())

    response = post_update(client, text_update("/start"))

    assert response.status_code == 503
    assert fake.sent == []
    assert assistant.calls == []


def test_the_api_works_without_telegram_settings(client):
    # conftest sets TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET to "".
    assert client.get("/health").status_code == 200
    assert client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10}).status_code == 201
    assert client.get(PRODUCTS_URL).status_code == 200


# --- Updates that are ignored ------------------------------------------------


@pytest.mark.parametrize(
    "update",
    [
        pytest.param({"update_id": 1}, id="no-message"),
        pytest.param(
            {"update_id": 1, "edited_message": text_update("hi")["message"]},
            id="edited-message",
        ),
        pytest.param(
            {
                "update_id": 1,
                "message": {
                    "message_id": 7,
                    "chat": {"id": CHAT_ID, "type": "private"},
                    "sticker": {"file_id": "abc"},
                },
            },
            id="sticker",
        ),
        pytest.param(
            {
                "update_id": 1,
                "message": {
                    "message_id": 7,
                    "chat": {"id": CHAT_ID, "type": "group"},
                    "new_chat_members": [{"id": 1, "is_bot": False, "first_name": "B"}],
                },
            },
            id="chat-join",
        ),
        pytest.param({"update_id": 1, "callback_query": {"id": "1"}}, id="callback"),
        pytest.param({"message": "not an object"}, id="malformed"),
    ],
)
def test_webhook_ignores_updates_without_message_text(client, sender, assistant, update):
    response = post_update(client, update)

    assert response.status_code == 200
    assert sender.sent == []
    assert assistant.calls == []


def test_webhook_ignores_a_body_that_is_not_json(client, sender, assistant):
    response = client.post(
        WEBHOOK_URL,
        content=b"not json",
        headers={SECRET_TOKEN_HEADER: WEBHOOK_SECRET, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert sender.sent == []


# --- Commands ----------------------------------------------------------------


@pytest.mark.parametrize("command", ["/start", "/help", "/start@CatalogBot", "/HELP"])
def test_start_and_help_send_the_welcome_text(client, sender, assistant, command):
    response = post_update(client, text_update(command))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.WELCOME_TEXT)]
    assert assistant.calls == []


def test_unknown_commands_get_the_welcome_text_instead_of_a_model_call(
    client, sender, assistant
):
    post_update(client, text_update("/settings"))

    assert sender.sent == [(CHAT_ID, telegram_bot.WELCOME_TEXT)]
    assert assistant.calls == []


# --- Catalog questions -------------------------------------------------------


def test_question_is_answered_with_the_catalog_and_sent_to_the_chat(
    client, sender, use_assistant
):
    fake = use_assistant(FakeAssistant(answer="Yes, 5 *keyboards* in stock."))
    client.post(PRODUCTS_URL, json={"name": "Mechanical Keyboard", "price": 89.99, "stock": 5})
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10})

    response = post_update(client, text_update("  Do you have keyboards?  ", chat_id=777))

    assert response.status_code == 200
    [call] = fake.calls
    assert call["question"] == "Do you have keyboards?"
    assert [product.name for product in call["products"]] == ["Mechanical Keyboard", "Mouse"]
    assert sender.sent == [(777, "Yes, 5 *keyboards* in stock.")]


class TransactionProbeAssistant:
    """Captures the request's DB session state at the moment answer() runs."""

    def __init__(self, sessions):
        self._sessions = sessions
        self.in_transaction = None

    def answer(self, question, products):
        self.in_transaction = [session.in_transaction() for session in self._sessions]
        return "ok"


def test_question_releases_the_db_connection_before_calling_the_assistant(
    client, sender, use_assistant, request_sessions
):
    probe = use_assistant(TransactionProbeAssistant(request_sessions))
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 3})
    request_sessions.clear()

    post_update(client, text_update("Do you have mice?"))

    assert probe.in_transaction == [False]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("x" * 501, id="too-long"),
        pytest.param("   ", id="whitespace-only"),
    ],
)
def test_invalid_question_gets_a_friendly_message_without_a_model_call(
    client, sender, assistant, text
):
    response = post_update(client, text_update(text))

    assert response.status_code == 200
    assert assistant.calls == []
    assert sender.sent == [(CHAT_ID, telegram_bot.INVALID_QUESTION_TEXT)]
    assert "500" in telegram_bot.INVALID_QUESTION_TEXT


def test_question_of_exactly_500_characters_is_answered(client, sender, assistant):
    post_update(client, text_update("x" * 500))

    assert len(assistant.calls) == 1


@pytest.mark.parametrize(
    ("error", "expected_text"),
    [
        pytest.param(
            AssistantQuotaExceeded("provider detail: quota"),
            telegram_bot.BUSY_TEXT,
            id="quota",
        ),
        pytest.param(
            AssistantUnavailable("provider detail: outage"),
            telegram_bot.UNAVAILABLE_TEXT,
            id="unavailable",
        ),
    ],
)
def test_assistant_errors_send_a_friendly_fallback(
    client, sender, use_assistant, error, expected_text
):
    use_assistant(FakeAssistant(error=error))

    response = post_update(client, text_update("Do you have keyboards?"))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, expected_text)]
    assert "provider detail" not in expected_text


def test_question_without_a_gemini_key_sends_the_not_configured_fallback(client, sender):
    # No assistant override: GEMINI_API_KEY is "" (see conftest).
    response = post_update(client, text_update("Do you have keyboards?"))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.NOT_CONFIGURED_TEXT)]


class FailingSession:
    """A DB session whose queries fail, like a paused Supabase project."""

    def __init__(self):
        self.rolled_back = False

    def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_database_failure_sends_a_fallback_and_still_acknowledges(
    client, sender, assistant
):
    session = FailingSession()
    previous_get_db = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = post_update(client, text_update("Do you have keyboards?"))
    finally:
        app.dependency_overrides[get_db] = previous_get_db

    assert response.status_code == 200
    assert assistant.calls == []
    assert sender.sent == [(CHAT_ID, telegram_bot.UNAVAILABLE_TEXT)]
    assert session.rolled_back


# --- Sender failures ---------------------------------------------------------


def test_sender_failure_is_logged_and_swallowed(
    client, telegram_env, use_sender, assistant, caplog
):
    failing = use_sender(FakeSender(error=httpx.ConnectError("network is unreachable")))

    with caplog.at_level(logging.WARNING, logger="telegram_bot"):
        response = post_update(client, text_update("Do you have keyboards?"))

    assert response.status_code == 200
    assert len(failing.sent) == 1
    assert str(CHAT_ID) in caplog.text
    assert "ConnectError" in caplog.text


def test_real_sender_failure_never_logs_the_bot_token(
    client, telegram_env, use_sender, assistant, caplog
):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    use_sender(HttpxTelegramSender(BOT_TOKEN, transport=httpx.MockTransport(refuse)))

    with caplog.at_level(logging.DEBUG):
        response = post_update(client, text_update("Do you have keyboards?"))

    assert response.status_code == 200
    assert str(CHAT_ID) in caplog.text
    assert BOT_TOKEN not in caplog.text
    assert "api.telegram.org" not in caplog.text


# --- HttpxTelegramSender (adapter) -------------------------------------------


def recording_transport(status_code=200):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status_code, json={"ok": status_code == 200})

    return requests, httpx.MockTransport(handler)


def test_adapter_posts_plain_text_to_the_bot_api():
    requests, transport = recording_transport()
    sender = HttpxTelegramSender(BOT_TOKEN, transport=transport)

    sender.send_message(CHAT_ID, "Hello *world*")

    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    assert json.loads(request.content) == {"chat_id": CHAT_ID, "text": "Hello *world*"}
    assert request.extensions["timeout"]["read"] == telegram_bot.SEND_TIMEOUT_SECONDS


def test_adapter_truncates_text_to_the_telegram_limit():
    requests, transport = recording_transport()
    sender = HttpxTelegramSender(BOT_TOKEN, transport=transport)

    sender.send_message(CHAT_ID, "x" * (MAX_MESSAGE_LENGTH + 10))

    assert len(json.loads(requests[0].content)["text"]) == MAX_MESSAGE_LENGTH


def test_adapter_raises_without_the_token_on_an_http_error():
    _, transport = recording_transport(status_code=403)
    sender = HttpxTelegramSender(BOT_TOKEN, transport=transport)

    with pytest.raises(TelegramSendError) as raised:
        sender.send_message(CHAT_ID, "Hello")

    assert "403" in str(raised.value)
    assert BOT_TOKEN not in str(raised.value)
    assert BOT_TOKEN not in repr(sender)


def test_get_telegram_sender_builds_the_httpx_adapter(telegram_env):
    config = telegram_bot.get_telegram_config()

    assert isinstance(get_telegram_sender(config), HttpxTelegramSender)
