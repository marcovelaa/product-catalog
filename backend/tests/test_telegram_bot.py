"""Telegram webhook tests. They never reach the network: the Bot API sender and
the catalog assistant are always faked (or use httpx.MockTransport)."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy.exc import OperationalError

import models
import telegram_bot
from catalog_assistant import AssistantQuotaExceeded, AssistantUnavailable
from database import get_db
from main import app
from telegram_bot import (
    MAX_MESSAGE_LENGTH,
    SECRET_TOKEN_HEADER,
    HttpxTelegramSender,
    TelegramSendError,
    get_telegram_admin_ids,
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


def text_update(text, chat_id=CHAT_ID, update_id=1001, sender_id=None):
    sender_id = chat_id if sender_id is None else sender_id
    return {
        "update_id": update_id,
        "message": {
            "message_id": 7,
            "date": 1_700_000_000,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": sender_id, "is_bot": False, "first_name": "Ana"},
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
def use_admins():
    def install(*admin_ids):
        app.dependency_overrides[get_telegram_admin_ids] = lambda: frozenset(admin_ids)

    yield install
    app.dependency_overrides.pop(get_telegram_admin_ids, None)


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


@pytest.mark.parametrize(
    "command",
    ["/start", "/help", "/ayuda", "/start@CatalogBot", "/HELP", "/ayuda por favor"],
)
def test_start_help_and_ayuda_send_the_welcome_text(client, sender, assistant, command):
    response = post_update(client, text_update(command))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.WELCOME_TEXT)]
    assert assistant.calls == []


def test_welcome_text_is_neutral_spanish_with_the_question_limits():
    text = telegram_bot.WELCOME_TEXT

    assert text.startswith("¡Hola! Soy el asistente del catálogo de productos.")
    assert "¿Tienen teclados por menos de 100?" in text
    assert "¿Qué productos están agotados?" in text
    assert "de 1 a 500 caracteres" in text
    assert "cerca de un minuto" in text
    assert "Hi!" not in text


def test_welcome_text_lists_the_public_commands_but_no_admin_commands():
    text = telegram_bot.WELCOME_TEXT

    assert "/productos" in text
    assert "/id" in text
    assert "/agregar" not in text
    assert "/editar" not in text


def test_admins_see_the_admin_commands_in_the_help_text(
    client, sender, assistant, use_admins
):
    use_admins(CHAT_ID)

    post_update(client, text_update("/ayuda"))

    [(chat_id, text)] = sender.sent
    assert chat_id == CHAT_ID
    assert text.startswith(telegram_bot.WELCOME_TEXT)
    assert "/agregar Nombre; precio; stock; url opcional" in text
    assert "/editar <id> campo=valor; campo=valor" in text
    assert "nombre, precio, stock, imagen" in text
    assert "punto y coma" in text
    assert len(text) <= MAX_MESSAGE_LENGTH


def test_non_admins_do_not_see_the_admin_commands(client, sender, assistant, use_admins):
    use_admins(999_999)

    post_update(client, text_update("/help"))

    assert sender.sent == [(CHAT_ID, telegram_bot.WELCOME_TEXT)]


def test_nobody_is_admin_when_the_allow_list_is_empty(client, sender, assistant, use_admins):
    use_admins()

    post_update(client, text_update("/help"))

    assert "/agregar" not in sender.sent[0][1]


def test_the_sender_id_decides_admin_rights_never_the_chat_id(
    client, sender, assistant, use_admins
):
    admin_id = 555
    use_admins(admin_id)

    # A group whose chat id equals an admin id, written by someone else.
    post_update(client, text_update("/help", chat_id=admin_id, sender_id=999, update_id=1))
    # The real admin writing in a group chat.
    post_update(client, text_update("/help", chat_id=-100123, sender_id=admin_id, update_id=2))

    (first_chat, first_text), (second_chat, second_text) = sender.sent
    assert first_chat == admin_id
    assert "/agregar" not in first_text
    assert second_chat == -100123
    assert "/agregar" in second_text


def test_messages_without_a_sender_are_never_admin(client, sender, assistant, use_admins):
    use_admins(CHAT_ID)
    update = text_update("/help")
    del update["message"]["from"]

    post_update(client, update)

    assert sender.sent == [(CHAT_ID, telegram_bot.WELCOME_TEXT)]


def test_admin_ids_come_from_the_environment_when_not_overridden(
    client, sender, assistant, monkeypatch
):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", f" abc, , {CHAT_ID} ,-7")

    post_update(client, text_update("/help", update_id=1))
    post_update(client, text_update("/help", update_id=2, sender_id=7))

    assert "/agregar" in sender.sent[0][1]
    assert "/agregar" not in sender.sent[1][1]


def test_commands_work_without_any_admin_configuration(client, sender, assistant):
    # conftest blanks TELEGRAM_ADMIN_IDS: nobody is admin, and nothing crashes.
    response = post_update(client, text_update("/help"))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.WELCOME_TEXT)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(None, set(), id="missing"),
        pytest.param("", set(), id="empty"),
        pytest.param("   ", set(), id="blank"),
        pytest.param("123", {123}, id="single"),
        pytest.param("123,456", {123, 456}, id="two"),
        pytest.param(" 123 , 456 ,, ,", {123, 456}, id="spaces-and-empty-items"),
        pytest.param("abc,123,4x5,1.5,0x10", {123}, id="junk-ignored"),
        pytest.param("-100123,0,5", {5}, id="non-positive-ignored"),
        pytest.param("١٢٣,7", {7}, id="non-ascii-digits-ignored"),
        pytest.param("1,1,1", {1}, id="duplicates"),
    ],
)
def test_parse_admin_ids_is_tolerant(raw, expected):
    assert telegram_bot.parse_admin_ids(raw) == frozenset(expected)


def test_get_telegram_admin_ids_reads_the_environment(monkeypatch):
    assert telegram_bot.get_telegram_admin_ids() == frozenset()

    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "10, 20")

    assert telegram_bot.get_telegram_admin_ids() == frozenset({10, 20})


# --- /id ---------------------------------------------------------------------


def test_id_replies_with_the_sender_id_to_anyone(client, sender, assistant):
    post_update(client, text_update("/id", chat_id=-100123, sender_id=987654321))

    assert sender.sent == [(-100123, "Tu ID de usuario de Telegram es 987654321.")]
    assert assistant.calls == []


@pytest.mark.parametrize("command", ["/id@CatalogBot", "/ID", "/id please"])
def test_id_accepts_the_bot_suffix_case_and_a_payload(client, sender, assistant, command):
    post_update(client, text_update(command, sender_id=31337))

    assert sender.sent == [(CHAT_ID, "Tu ID de usuario de Telegram es 31337.")]


def test_id_without_a_sender_says_the_id_is_not_available(client, sender, assistant):
    update = text_update("/id")
    del update["message"]["from"]

    response = post_update(client, update)

    assert response.status_code == 200
    [(chat_id, text)] = sender.sent
    assert chat_id == CHAT_ID
    assert "no está disponible" in text
    assert "Tu ID de usuario" not in text


def test_questions_still_work_without_a_sender_field(client, sender, use_assistant):
    fake = use_assistant(FakeAssistant(answer="Yes."))
    update = text_update("Do you have keyboards?")
    del update["message"]["from"]

    post_update(client, update)

    assert len(fake.calls) == 1
    assert sender.sent == [(CHAT_ID, "Yes.")]


def test_a_channel_post_style_payload_without_from_is_accepted(client, sender, assistant):
    update = {
        "update_id": 3,
        "message": {"message_id": 1, "chat": {"id": -1001, "type": "channel"}, "text": "/start"},
    }

    assert post_update(client, update).status_code == 200
    assert sender.sent == [(-1001, telegram_bot.WELCOME_TEXT)]


# --- /productos --------------------------------------------------------------


def add_product(db, name, price, stock):
    product = models.Product(name=name, price=price, stock=stock)
    db.add(product)
    db.commit()
    return product


def test_productos_lists_products_in_id_order_with_the_exact_format(
    client, sender, assistant
):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 25.5, "stock": 3})
    client.post(PRODUCTS_URL, json={"name": "Teclado", "price": 100, "stock": 0})
    client.post(PRODUCTS_URL, json={"name": "Monitor", "price": 199.99, "stock": 12})

    response = post_update(client, text_update("/productos"))

    assert response.status_code == 200
    assert sender.sent == [
        (
            CHAT_ID,
            "#1 Mouse: 25,50 · 3 en stock\n"
            "#2 Teclado: 100,00 · agotado\n"
            "#3 Monitor: 199,99 · 12 en stock",
        )
    ]
    assert assistant.calls == []


@pytest.mark.parametrize("command", ["/productos@CatalogBot", "/PRODUCTOS", "/productos ya"])
def test_productos_accepts_the_bot_suffix_case_and_a_payload(
    client, sender, assistant, command
):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 1})

    post_update(client, text_update(command))

    assert sender.sent == [(CHAT_ID, "#1 Mouse: 10,00 · 1 en stock")]


def test_productos_is_open_to_non_admins(client, sender, assistant, use_admins):
    use_admins(1)
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 1})

    post_update(client, text_update("/productos", sender_id=2))

    assert sender.sent == [(CHAT_ID, "#1 Mouse: 10,00 · 1 en stock")]


def test_productos_with_an_empty_catalog_sends_a_friendly_message(client, sender, assistant):
    post_update(client, text_update("/productos"))

    assert sender.sent == [(CHAT_ID, telegram_bot.NO_PRODUCTS_TEXT)]
    assert "no hay productos" in telegram_bot.NO_PRODUCTS_TEXT.lower()


def test_productos_truncates_a_long_list_under_the_telegram_limit(
    client, sender, assistant, db_session
):
    total = 40
    for index in range(total):
        add_product(db_session, f"Producto {index:02d} " + "x" * 180, 9.99, 5)

    post_update(client, text_update("/productos"))

    [(chat_id, text)] = sender.sent
    lines = text.split("\n")
    shown = [line for line in lines if line.startswith("#")]
    assert chat_id == CHAT_ID
    assert len(text) <= MAX_MESSAGE_LENGTH
    assert 0 < len(shown) < total
    assert shown[0].startswith("#1 Producto 00")
    assert lines[-1] == f"… y {total - len(shown)} más. Pregunta por uno concreto."
    assert len(lines) == len(shown) + 1


def test_productos_does_not_truncate_a_list_that_fits(client, sender, assistant, db_session):
    for index in range(10):
        add_product(db_session, f"Producto {index}", 1, 1)

    post_update(client, text_update("/productos"))

    text = sender.sent[0][1]
    assert text.count("\n") == 9
    assert "más" not in text


def test_productos_database_failure_sends_the_unavailable_text(client, sender, assistant):
    session = FailingSession()
    previous_get_db = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = post_update(client, text_update("/productos"))
    finally:
        app.dependency_overrides[get_db] = previous_get_db

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.UNAVAILABLE_TEXT)]
    assert session.rolled_back


def test_productos_failure_logs_the_chat_id_without_error_details(
    client, sender, assistant, caplog
):
    session = FailingSession()
    previous_get_db = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = lambda: session
    try:
        with caplog.at_level(logging.WARNING):
            post_update(client, text_update("/productos"))
    finally:
        app.dependency_overrides[get_db] = previous_get_db

    assert str(CHAT_ID) in caplog.text
    assert "OperationalError" in caplog.text
    assert "server closed the connection" not in caplog.text


def test_productos_releases_the_db_connection(client, sender, assistant, request_sessions):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 3})
    request_sessions.clear()

    post_update(client, text_update("/productos"))

    assert [session.in_transaction() for session in request_sessions] == [False]


# --- Other commands ----------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "/settings",
        "/agregar Mouse; 10; 5",
        "/editar 1 precio=12",
        "/agregar@CatalogBot Mouse; 10; 5",
        "/AGREGAR",
        "/",
    ],
)
def test_other_commands_get_the_not_available_reply(
    client, sender, assistant, use_admins, command
):
    use_admins(CHAT_ID)

    response = post_update(client, text_update(command))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.UNKNOWN_COMMAND_TEXT)]
    assert assistant.calls == []
    assert "/ayuda" in telegram_bot.UNKNOWN_COMMAND_TEXT


def test_unimplemented_admin_commands_do_not_write_to_the_database(
    client, sender, assistant, use_admins
):
    use_admins(CHAT_ID)

    post_update(client, text_update("/agregar Mouse; 10; 5"))

    assert client.get(PRODUCTS_URL).json() == []


@pytest.mark.parametrize("command", ["/id", "/productos", "/ayuda", "/agregar x"])
def test_duplicate_deliveries_of_commands_yield_one_reply(client, sender, assistant, command):
    first = post_update(client, text_update(command, update_id=88))
    second = post_update(client, text_update(command, update_id=88))

    assert first.status_code == second.status_code == 200
    assert len(sender.sent) == 1


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
    assert sender.sent == [
        (CHAT_ID, "Por favor, envía una pregunta de entre 1 y 500 caracteres.")
    ]


def test_question_of_exactly_500_characters_is_answered(client, sender, assistant):
    post_update(client, text_update("x" * 500))

    assert len(assistant.calls) == 1


@pytest.mark.parametrize(
    ("error", "expected_text"),
    [
        pytest.param(
            AssistantQuotaExceeded("provider detail: quota"),
            "El asistente está ocupado en este momento. Inténtalo de nuevo en un minuto.",
            id="quota",
        ),
        pytest.param(
            AssistantUnavailable("provider detail: outage"),
            "Lo siento, no he podido responder ahora mismo. "
            "Inténtalo de nuevo en un minuto.",
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
    assert sender.sent == [
        (
            CHAT_ID,
            "El asistente del catálogo aún no está configurado. "
            "Inténtalo de nuevo más tarde.",
        )
    ]


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
    assert sender.sent == [
        (
            CHAT_ID,
            "Lo siento, no he podido responder ahora mismo. "
            "Inténtalo de nuevo en un minuto.",
        )
    ]
    assert session.rolled_back


# --- Duplicate deliveries (update_id de-duplication) ------------------------------


class QuerySpySession:
    """A DB session that fails loudly if anything tries to query it."""

    def __init__(self):
        self.executed = 0

    def execute(self, *args, **kwargs):
        self.executed += 1
        raise AssertionError("a duplicate update must not query the database")

    def rollback(self):
        pass

    def close(self):
        pass


def test_same_update_id_sent_twice_yields_exactly_one_reply(client, sender, assistant):
    first = post_update(client, text_update("Do you have keyboards?", update_id=55))
    second = post_update(client, text_update("Do you have keyboards?", update_id=55))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(sender.sent) == 1
    assert len(assistant.calls) == 1


def test_different_update_ids_each_get_a_reply(client, sender, assistant):
    post_update(client, text_update("/start", update_id=1))
    post_update(client, text_update("/start", update_id=2))

    assert len(sender.sent) == 2


def test_duplicate_update_does_not_call_the_assistant_or_the_database(
    client, sender, assistant
):
    post_update(client, text_update("Do you have keyboards?", update_id=9))
    spy = QuerySpySession()
    previous_get_db = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = lambda: spy
    try:
        response = post_update(client, text_update("Do you have keyboards?", update_id=9))
    finally:
        app.dependency_overrides[get_db] = previous_get_db

    assert response.status_code == 200
    assert spy.executed == 0
    assert len(assistant.calls) == 1
    assert len(sender.sent) == 1


def test_update_is_marked_as_seen_even_when_it_has_no_text(client, sender, assistant):
    post_update(client, {"update_id": 77, "callback_query": {"id": "1"}})

    assert post_update(client, text_update("/start", update_id=77)).status_code == 200
    assert sender.sent == []


def test_webhook_still_works_for_updates_without_an_update_id(client, sender, assistant):
    update = text_update("/start")
    del update["update_id"]

    post_update(client, update)
    post_update(client, update)

    # Nothing to de-duplicate on: each delivery is handled as before.
    assert len(sender.sent) == 2


def test_unauthenticated_request_does_not_mark_the_update_as_seen(
    client, sender, assistant
):
    post_update(client, text_update("/start", update_id=5), secret="wrong-secret")

    post_update(client, text_update("/start", update_id=5))

    assert len(sender.sent) == 1


def test_recent_updates_reports_a_new_id_once():
    recent = telegram_bot.RecentUpdates()

    assert recent.first_time(1) is True
    assert recent.first_time(1) is False
    assert recent.first_time(2) is True


def test_recent_updates_is_bounded_and_evicts_the_oldest_first():
    recent = telegram_bot.RecentUpdates(max_entries=3)
    for update_id in (1, 2, 3, 4):
        assert recent.first_time(update_id) is True

    assert len(recent) == 3
    assert recent.first_time(1) is True  # evicted, so it counts as new again
    assert recent.first_time(4) is False  # recent ids are still remembered


def test_recent_updates_default_capacity_is_one_thousand():
    recent = telegram_bot.RecentUpdates()
    for update_id in range(telegram_bot.MAX_RECENT_UPDATES + 5):
        recent.first_time(update_id)

    assert telegram_bot.MAX_RECENT_UPDATES == 1000
    assert len(recent) == telegram_bot.MAX_RECENT_UPDATES


def test_recent_updates_rejects_a_non_positive_capacity():
    with pytest.raises(ValueError):
        telegram_bot.RecentUpdates(max_entries=0)


def test_recent_updates_is_safe_under_concurrent_use():
    recent = telegram_bot.RecentUpdates()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(recent.first_time, [42] * 200))

    assert results.count(True) == 1


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
