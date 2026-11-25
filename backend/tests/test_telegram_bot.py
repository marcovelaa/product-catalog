"""Telegram webhook tests. They never reach the network: the Bot API sender and
the catalog assistant are always faked (or use httpx.MockTransport)."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy.exc import OperationalError

import conversation_memory
import models
import product_service
import slack_alerts
import telegram_bot
from catalog_assistant import AssistantQuotaExceeded, AssistantUnavailable, ConversationTurn
from conftest import test_engine
from database import get_db
from main import app
from telegram_bot import (
    MAX_MESSAGE_LENGTH,
    SECRET_TOKEN_HEADER,
    HttpxTelegramSender,
    InputError,
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

    def answer(self, question, products, history=()):
        self.calls.append(
            {"question": question, "products": list(products), "history": list(history)}
        )
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/agregar Mouse; 25,50; 12", ("agregar", "Mouse; 25,50; 12")),
        ("/agregar\nMouse; 25,50; 12", ("agregar", "Mouse; 25,50; 12")),
        ("/agregar\tMouse; 25,50; 12", ("agregar", "Mouse; 25,50; 12")),
        ("/agregar \n  Mouse", ("agregar", "Mouse")),
        ("/editar@MiBot 3 precio=30", ("editar", "3 precio=30")),
        ("/ID", ("id", "")),
        ("/id\n", ("id", "")),
        ("/", ("", "")),
    ],
)
def test_parse_command_splits_on_any_whitespace(text, expected):
    assert telegram_bot.parse_command(text) == expected


def test_parse_command_ignores_plain_text():
    assert telegram_bot.parse_command("¿Cuánto cuesta el mouse?") is None


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
    assert "bolivianos (Bs)" in text
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
            "#1 Mouse: Bs 25,50 · 3 en stock\n"
            "#2 Teclado: Bs 100,00 · agotado\n"
            "#3 Monitor: Bs 199,99 · 12 en stock",
        )
    ]
    assert assistant.calls == []


@pytest.mark.parametrize("command", ["/productos@CatalogBot", "/PRODUCTOS", "/productos ya"])
def test_productos_accepts_the_bot_suffix_case_and_a_payload(
    client, sender, assistant, command
):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 1})

    post_update(client, text_update(command))

    assert sender.sent == [(CHAT_ID, "#1 Mouse: Bs 10,00 · 1 en stock")]


def test_productos_is_open_to_non_admins(client, sender, assistant, use_admins):
    use_admins(1)
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 1})

    post_update(client, text_update("/productos", sender_id=2))

    assert sender.sent == [(CHAT_ID, "#1 Mouse: Bs 10,00 · 1 en stock")]


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


@pytest.mark.parametrize("command", ["/settings", "/borrar 1", "/"])
def test_other_commands_get_the_not_available_reply(
    client, sender, assistant, use_admins, command
):
    use_admins(CHAT_ID)

    response = post_update(client, text_update(command))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.UNKNOWN_COMMAND_TEXT)]
    assert assistant.calls == []
    assert "/ayuda" in telegram_bot.UNKNOWN_COMMAND_TEXT


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

    def answer(self, question, products, history=()):
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


# --- Admin write commands: field validation -----------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("25,50", 25.5),
        ("25.50", 25.5),
        ("25", 25.0),
        ("0", 0.0),
        ("0,5", 0.5),
        ("10.0", 10.0),
        ("  7  ", 7.0),
        ("1234567", 1234567.0),
    ],
)
def test_parse_price_accepts_one_decimal_comma_or_dot(raw, expected):
    assert telegram_bot.parse_price(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1.000", "1,000", "1,000.50", "1.2.3", "1,5,0", "0x1A", "0b11", "0o7", "1e3",
        "1E3", "1_000", "Infinity", "inf", "nan", "", "   ", "abc", "5,", ".5", ",5",
        "１２", "٣", "+5", "5 0", "1.234", "9" * 400,
    ],
)
def test_parse_price_rejects_anything_else(raw):
    with pytest.raises(InputError, match="precio"):
        telegram_bot.parse_price(raw)


@pytest.mark.parametrize("raw", ["-5", "-0,50", "-0"])
def test_parse_price_says_a_negative_price_is_not_allowed(raw):
    with pytest.raises(InputError, match="negativ"):
        telegram_bot.parse_price(raw)


@pytest.mark.parametrize(
    "raw, expected",
    [("0", 0), ("12", 12), (" 5 ", 5), ("2147483647", 2_147_483_647), ("007", 7)],
)
def test_parse_stock_accepts_whole_numbers_in_the_integer_range(raw, expected):
    assert telegram_bot.parse_stock(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["2147483648", "-1", "1.5", "1,5", "1e3", "0x10", "abc", "", "٣", "9" * 5000],
)
def test_parse_stock_rejects_everything_else(raw):
    with pytest.raises(InputError, match="stock"):
        telegram_bot.parse_stock(raw)


@pytest.mark.parametrize(
    "raw, expected",
    [("x", "x"), ("  Mouse  ", "Mouse"), ("a" * 200, "a" * 200), ("Mouse \n  Pro", "Mouse Pro")],
)
def test_parse_name_trims_and_collapses_whitespace(raw, expected):
    assert telegram_bot.parse_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\n", "a" * 201])
def test_parse_name_rejects_empty_and_too_long_names(raw):
    with pytest.raises(InputError, match="nombre"):
        telegram_bot.parse_name(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "http://example.com/a.png",
        "https://example.com/a.png?x=1&y=2",
        "HTTPS://Example.com/A",
        "https://example.com/" + "x" * (2048 - len("https://example.com/")),
    ],
)
def test_parse_image_url_accepts_http_and_https(raw):
    assert telegram_bot.parse_image_url(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        "javascript:alert(1)",
        "ftp://example.com/a.png",
        "example.com/a.png",
        "http://",
        "https:///a.png",
        "http://example.com/ a.png",
        "data:image/png;base64,AAAA",
        "file:///etc/passwd",
        "http://[abc",
        "https://example.com/" + "x" * 2048,
    ],
)
def test_parse_image_url_rejects_everything_else(raw):
    with pytest.raises(InputError, match="imagen"):
        telegram_bot.parse_image_url(raw)


# --- Admin write commands: parsing ---------------------------------------------


def test_parse_add_reads_name_price_stock_and_image():
    data = telegram_bot.parse_add("Mouse inalámbrico; 25,50; 12; https://example.com/m.png")

    assert (data.name, data.price, data.stock, data.image_url) == (
        "Mouse inalámbrico", 25.5, 12, "https://example.com/m.png",
    )


def test_parse_add_defaults_stock_to_zero_and_image_to_none():
    data = telegram_bot.parse_add("Mouse; 10")

    assert (data.stock, data.image_url) == (0, None)


def test_parse_add_trims_the_whitespace_around_fields():
    data = telegram_bot.parse_add("  Mouse  ;\n 10 ;  5  ")

    assert (data.name, data.price, data.stock) == ("Mouse", 10.0, 5)


def test_parse_add_lets_the_stock_be_skipped_to_give_an_image():
    data = telegram_bot.parse_add("Mouse; 10; ; https://example.com/m.png")

    assert (data.stock, data.image_url) == (0, "https://example.com/m.png")


def test_parse_add_treats_a_trailing_semicolon_as_no_image():
    data = telegram_bot.parse_add("Mouse; 10; 5;")

    assert (data.stock, data.image_url) == (5, None)


def test_parse_add_keeps_an_equals_sign_inside_the_name():
    assert telegram_bot.parse_add("A=B; 10").name == "A=B"


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "Mouse",
        "Mouse; 10; 5; https://example.com/a.png; extra",
        "Mouse; 10; 5;;",
        ";;;;",
    ],
)
def test_parse_add_replies_with_the_usage_for_a_wrong_field_count(payload):
    with pytest.raises(InputError) as error:
        telegram_bot.parse_add(payload)

    assert telegram_bot.ADD_USAGE in str(error.value)


@pytest.mark.parametrize(
    "payload, field",
    [
        ("; 10; 5", "nombre"),
        ("Mouse; ; 5", "precio"),
        ("Mouse;;", "precio"),
        ("Mouse; 1.000; 5", "precio"),
        ("Mouse; -5; 5", "precio"),
        ("Mouse; 10; -1", "stock"),
        ("Mouse; 10; 2147483648", "stock"),
        ("Mouse; 10; 5; javascript:alert(1)", "imagen"),
        ("x" * 201 + "; 10", "nombre"),
    ],
)
def test_parse_add_names_the_invalid_field(payload, field):
    with pytest.raises(InputError, match=field):
        telegram_bot.parse_add(payload)


def test_parse_edit_builds_a_partial_change_with_only_the_given_fields():
    product_id, changes = telegram_bot.parse_edit("3 precio=19,90; stock=8")

    assert product_id == 3
    assert changes.model_fields_set == {"price", "stock"}
    assert (changes.price, changes.stock) == (19.9, 8)


def test_parse_edit_field_names_are_case_insensitive():
    _, changes = telegram_bot.parse_edit("3 PRECIO=5; Nombre=Mouse; sTock=2; IMAGEN=-")

    assert changes.model_fields_set == {"price", "name", "stock", "image_url"}


def test_parse_edit_splits_each_field_on_the_first_equals_only():
    _, changes = telegram_bot.parse_edit(
        "3 nombre=a=b; imagen=https://example.com/a?b=c"
    )

    assert changes.name == "a=b"
    assert changes.image_url == "https://example.com/a?b=c"


@pytest.mark.parametrize("payload", ["3 imagen=", "3 imagen=-", "3 imagen=  -  "])
def test_parse_edit_clears_the_image_with_an_empty_value_or_a_dash(payload):
    _, changes = telegram_bot.parse_edit(payload)

    assert changes.model_fields_set == {"image_url"}
    assert changes.image_url is None


@pytest.mark.parametrize("payload", ["3 precio=5;", "3\nprecio=5", "3   precio=5 ;; "])
def test_parse_edit_tolerates_newlines_and_stray_semicolons(payload):
    product_id, changes = telegram_bot.parse_edit(payload)

    assert (product_id, changes.price) == (3, 5.0)


@pytest.mark.parametrize(
    "payload", ["0 precio=5", "-1 precio=5", "abc precio=5", "1.5 precio=5", "9" * 30 + " precio=5"]
)
def test_parse_edit_rejects_an_id_that_is_not_a_positive_integer(payload):
    with pytest.raises(InputError, match="id"):
        telegram_bot.parse_edit(payload)


@pytest.mark.parametrize("payload", ["", "3", "3 ;", "   "])
def test_parse_edit_replies_with_the_usage_when_nothing_is_given(payload):
    with pytest.raises(InputError) as error:
        telegram_bot.parse_edit(payload)

    assert telegram_bot.EDIT_USAGE in str(error.value)


def test_parse_edit_lists_the_valid_fields_for_an_unknown_one():
    with pytest.raises(InputError) as error:
        telegram_bot.parse_edit("3 color=rojo")

    message = str(error.value)
    assert "color" in message
    assert "nombre, precio, stock, imagen" in message


def test_parse_edit_rejects_a_repeated_field():
    with pytest.raises(InputError, match="precio.*dos veces"):
        telegram_bot.parse_edit("3 precio=5; PRECIO=6")


@pytest.mark.parametrize("payload", ["3 precio", "3 precio=5; stock", "3 =5"])
def test_parse_edit_requires_an_equals_sign_with_a_field_name(payload):
    with pytest.raises(InputError, match="campo=valor"):
        telegram_bot.parse_edit(payload)


@pytest.mark.parametrize(
    "payload, field",
    [
        ("3 precio=abc", "precio"),
        ("3 precio=1.000", "precio"),
        ("3 stock=-1", "stock"),
        ("3 stock=2147483648", "stock"),
        ("3 nombre=", "nombre"),
        ("3 nombre=" + "x" * 201, "nombre"),
        ("3 imagen=javascript:alert(1)", "imagen"),
    ],
)
def test_parse_edit_names_the_invalid_field(payload, field):
    with pytest.raises(InputError, match=field):
        telegram_bot.parse_edit(payload)


# --- Admin write commands: through the webhook ---------------------------------


ADMIN_ID = 555


class FakeNotifier:
    """In-memory SlackNotifier that records every message."""

    def __init__(self, error=None):
        self._error = error
        self.sent = []

    def post_message(self, text):
        self.sent.append(text)
        if self._error is not None:
            raise self._error


@pytest.fixture
def use_notifier():
    def install(notifier):
        app.dependency_overrides[slack_alerts.get_slack_notifier] = lambda: notifier
        return notifier

    yield install
    app.dependency_overrides.pop(slack_alerts.get_slack_notifier, None)


@pytest.fixture
def admin(use_admins):
    """Make the default test chat's sender an admin."""
    use_admins(CHAT_ID)


class ForbiddenSession:
    """A session that fails loudly if anything touches the database."""

    def __getattr__(self, name):
        if name in {"rollback", "close"}:
            return lambda: None
        raise AssertionError(f"the database must not be used (session.{name})")


class WriteFailingSession:
    """A session whose reads and writes fail, like a paused Supabase project."""

    def __init__(self):
        self.rolled_back = False

    def _fail(self, *args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("server closed the connection"))

    add = get = commit = execute = refresh = _fail

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def use_session(session):
    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = lambda: session
    return previous


def stored_products(db):
    db.expire_all()
    return db.query(models.Product).order_by(models.Product.id).all()


def test_admin_adds_a_product_and_gets_it_back_in_the_list_format(
    client, sender, assistant, admin, db_session
):
    response = post_update(
        client, text_update("/agregar Mouse inalámbrico; 25,50; 12; https://example.com/m.png")
    )

    assert response.status_code == 200
    assert sender.sent == [
        (CHAT_ID, "Producto agregado: #1 Mouse inalámbrico: Bs 25,50 · 12 en stock.")
    ]
    [product] = stored_products(db_session)
    assert (product.name, float(product.price), product.stock, product.image_url) == (
        "Mouse inalámbrico", 25.5, 12, "https://example.com/m.png",
    )
    assert assistant.calls == []


def test_add_without_stock_creates_an_out_of_stock_product(
    client, sender, assistant, admin, db_session
):
    post_update(client, text_update("/agregar Mouse; 10"))

    assert sender.sent == [(CHAT_ID, "Producto agregado: #1 Mouse: Bs 10,00 · agotado.")]
    assert stored_products(db_session)[0].stock == 0


@pytest.mark.parametrize(
    "command",
    ["/agregar\nMouse; 10; 5", "/agregar@CatalogBot Mouse; 10; 5", "/AGREGAR Mouse; 10; 5"],
)
def test_add_accepts_a_newline_the_bot_suffix_and_any_case(
    client, sender, assistant, admin, db_session, command
):
    post_update(client, text_update(command))

    assert [product.name for product in stored_products(db_session)] == ["Mouse"]
    assert sender.sent[0][1].startswith("Producto agregado: #1 Mouse")


def test_admin_edits_a_product_and_sees_the_whole_result(
    client, sender, assistant, admin, db_session
):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 25.5, "stock": 12,
                                    "image_url": "https://example.com/m.png"})

    post_update(client, text_update("/editar 1 precio=19,90; stock=8"))

    assert sender.sent == [(CHAT_ID, "Producto actualizado: #1 Mouse: Bs 19,90 · 8 en stock.")]
    [product] = stored_products(db_session)
    assert (product.name, float(product.price), product.stock, product.image_url) == (
        "Mouse", 19.9, 8, "https://example.com/m.png",
    )


def test_edit_renames_and_clears_the_image(client, sender, assistant, admin, db_session):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 1,
                                    "image_url": "https://example.com/m.png"})

    post_update(client, text_update("/editar 1 nombre=Mouse Pro; imagen=-"))

    assert sender.sent == [(CHAT_ID, "Producto actualizado: #1 Mouse Pro: Bs 10,00 · 1 en stock.")]
    [product] = stored_products(db_session)
    assert (product.name, product.image_url) == ("Mouse Pro", None)


def test_edit_of_a_missing_product_says_so(client, sender, assistant, admin, db_session):
    post_update(client, text_update("/editar 99 stock=1"))

    assert sender.sent == [(CHAT_ID, "No existe el producto #99.")]
    assert stored_products(db_session) == []


@pytest.mark.parametrize(
    "command, text_part",
    [
        ("/agregar", "Uso: /agregar"),
        ("/agregar Mouse", "Uso: /agregar"),
        ("/agregar Mouse; 1.000", "precio"),
        ("/agregar Mouse; 10; 5; javascript:alert(1)", "imagen"),
        ("/editar", "Uso: /editar"),
        ("/editar 1", "Uso: /editar"),
        ("/editar 0 stock=1", "id"),
        ("/editar 1 color=rojo", "color"),
        ("/editar 1 precio=0x1A", "precio"),
    ],
)
def test_invalid_input_gets_a_clear_message_and_writes_nothing(
    client, sender, assistant, admin, db_session, command, text_part
):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 1})

    response = post_update(client, text_update(command))

    assert response.status_code == 200
    [(chat_id, text)] = sender.sent
    assert chat_id == CHAT_ID
    assert text_part in text
    assert len(text) <= MAX_MESSAGE_LENGTH
    [product] = stored_products(db_session)
    assert (product.name, float(product.price), product.stock) == ("Mouse", 10.0, 1)


@pytest.mark.parametrize(
    "command",
    [
        "/agregar Mouse; 10; 5",
        "/agregar",
        "/agregar Mouse; 1.000",
        "/editar 1 precio=5",
        "/editar basura",
        "/agregar@CatalogBot Mouse; 10; 5",
    ],
)
def test_non_admins_are_refused_without_touching_the_database(
    client, sender, assistant, use_admins, use_notifier, command
):
    use_admins(999_999)
    notifier = use_notifier(FakeNotifier())
    previous = use_session(ForbiddenSession())
    try:
        response = post_update(client, text_update(command))
    finally:
        app.dependency_overrides[get_db] = previous

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.ADMIN_ONLY_TEXT)]
    assert notifier.sent == []
    assert assistant.calls == []


def test_the_refusal_reveals_no_syntax_details():
    text = telegram_bot.ADMIN_ONLY_TEXT

    assert text == "Solo el administrador puede usar este comando."
    assert ";" not in text and "precio" not in text and "campo" not in text


def test_everyone_is_refused_when_the_allow_list_is_empty(
    client, sender, assistant, use_admins, db_session
):
    use_admins()

    post_update(client, text_update("/agregar Mouse; 10; 5", sender_id=ADMIN_ID))
    post_update(client, text_update("/editar 1 stock=1", update_id=1002))

    assert sender.sent == [(CHAT_ID, telegram_bot.ADMIN_ONLY_TEXT)] * 2
    assert stored_products(db_session) == []


def test_a_group_chat_id_that_equals_an_admin_id_grants_nothing(
    client, sender, assistant, use_admins, db_session
):
    use_admins(CHAT_ID)  # the allow-list holds an id that is also the chat's id

    post_update(client, text_update("/agregar Mouse; 10; 5", chat_id=CHAT_ID, sender_id=777))

    assert sender.sent == [(CHAT_ID, telegram_bot.ADMIN_ONLY_TEXT)]
    assert stored_products(db_session) == []


def test_a_message_without_a_sender_is_refused(client, sender, assistant, use_admins):
    use_admins(CHAT_ID)
    update = text_update("/agregar Mouse; 10; 5")
    del update["message"]["from"]

    post_update(client, update)

    assert sender.sent == [(CHAT_ID, telegram_bot.ADMIN_ONLY_TEXT)]


def test_admin_can_write_from_a_group_where_only_they_are_listed(
    client, sender, assistant, use_admins, db_session
):
    use_admins(ADMIN_ID)

    post_update(client, text_update("/agregar Mouse; 10; 5", chat_id=-1001, sender_id=ADMIN_ID))

    assert sender.sent == [(-1001, "Producto agregado: #1 Mouse: Bs 10,00 · 5 en stock.")]


@pytest.mark.parametrize("command", ["/agregar Mouse; 10; 5", "/editar 1 stock=2"])
def test_database_failure_on_a_write_sends_the_unavailable_text(
    client, sender, assistant, admin, use_notifier, command
):
    notifier = use_notifier(FakeNotifier())
    session = WriteFailingSession()
    previous = use_session(session)
    try:
        response = post_update(client, text_update(command))
    finally:
        app.dependency_overrides[get_db] = previous

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.UNAVAILABLE_TEXT)]
    assert session.rolled_back
    assert notifier.sent == []


def test_write_failure_logs_the_chat_id_and_error_class_only(
    client, sender, assistant, admin, caplog
):
    previous = use_session(WriteFailingSession())
    try:
        with caplog.at_level(logging.WARNING):
            post_update(client, text_update("/agregar Secret product; 10; 5"))
    finally:
        app.dependency_overrides[get_db] = previous

    assert str(CHAT_ID) in caplog.text
    assert "OperationalError" in caplog.text
    assert "server closed the connection" not in caplog.text
    assert "Secret product" not in caplog.text


@pytest.mark.parametrize("command", ["/agregar Mouse; 10; 5", "/editar 1 stock=2"])
def test_a_write_leaves_no_session_in_a_transaction(
    client, sender, assistant, admin, request_sessions, command
):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 1})
    request_sessions.clear()

    post_update(client, text_update(command))

    assert [session.in_transaction() for session in request_sessions] == [False]


# --- Admin write commands: Slack alert ------------------------------------------


def test_add_fires_exactly_one_slack_alert_in_the_usual_format(
    client, sender, assistant, admin, use_notifier
):
    notifier = use_notifier(FakeNotifier())

    post_update(client, text_update("/agregar Mouse; 25,50; 12"))

    assert notifier.sent == [slack_alerts.format_product_created("Mouse", 1, 25.5, 12)]
    assert notifier.sent == ["New product: Mouse (id 1) - price Bs 25.50, stock 12"]


def test_the_slack_alert_neutralizes_markup_in_the_name(
    client, sender, assistant, admin, use_notifier
):
    notifier = use_notifier(FakeNotifier())

    post_update(client, text_update("/agregar <!channel> hola & adiós; 1"))

    assert notifier.sent == [
        "New product: &lt;!channel&gt; hola &amp; adiós (id 1) - price Bs 1.00, stock 0"
    ]


def test_a_failing_slack_notifier_does_not_change_the_telegram_reply(
    client, sender, assistant, admin, use_notifier, db_session
):
    use_notifier(FakeNotifier(error=RuntimeError("slack is down")))

    response = post_update(client, text_update("/agregar Mouse; 10; 5"))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, "Producto agregado: #1 Mouse: Bs 10,00 · 5 en stock.")]
    assert len(stored_products(db_session)) == 1


def test_add_works_without_a_slack_webhook(client, sender, assistant, admin):
    response = post_update(client, text_update("/agregar Mouse; 10; 5"))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, "Producto agregado: #1 Mouse: Bs 10,00 · 5 en stock.")]


def test_edit_does_not_fire_a_slack_alert(client, sender, assistant, admin, use_notifier):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 1})
    notifier = use_notifier(FakeNotifier())

    post_update(client, text_update("/editar 1 stock=2"))
    post_update(client, text_update("/editar 99 stock=2", update_id=1002))

    assert notifier.sent == []


def test_invalid_add_fires_no_slack_alert(client, sender, assistant, admin, use_notifier):
    notifier = use_notifier(FakeNotifier())

    post_update(client, text_update("/agregar Mouse; abc"))

    assert notifier.sent == []


def test_the_slack_alert_runs_without_a_database_session_in_a_transaction(
    client, sender, assistant, admin, use_notifier, request_sessions
):
    states = []

    class ProbeNotifier(FakeNotifier):
        def post_message(self, text):
            states.append([session.in_transaction() for session in request_sessions])

    use_notifier(ProbeNotifier())

    post_update(client, text_update("/agregar Mouse; 10; 5"))

    assert states == [[False]]


# --- Admin write commands: duplicates and the public API ---------------------------


def test_a_redelivered_add_creates_only_one_product(
    client, sender, assistant, admin, use_notifier, db_session
):
    notifier = use_notifier(FakeNotifier())

    first = post_update(client, text_update("/agregar Mouse; 10; 5", update_id=77))
    second = post_update(client, text_update("/agregar Mouse; 10; 5", update_id=77))

    assert first.status_code == second.status_code == 200
    assert len(stored_products(db_session)) == 1
    assert len(sender.sent) == 1
    assert len(notifier.sent) == 1


@pytest.mark.parametrize("method", ["patch", "put", "delete"])
def test_the_public_api_has_no_route_to_edit_or_delete_products(client, method):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10})

    for url in (f"{PRODUCTS_URL}/1", PRODUCTS_URL):
        assert getattr(client, method)(url).status_code in (404, 405)


def test_the_bot_writes_through_the_shared_product_service(
    client, sender, assistant, admin, monkeypatch
):
    calls = []
    real_create = product_service.create_product
    monkeypatch.setattr(
        product_service, "create_product",
        lambda db, data: calls.append(data.name) or real_create(db, data),
    )

    post_update(client, text_update("/agregar Mouse; 10; 5"))

    assert calls == ["Mouse"]


def test_the_admin_help_text_matches_the_implemented_syntax():
    section = telegram_bot.ADMIN_HELP_SECTION

    assert telegram_bot.ADD_SYNTAX in section
    assert telegram_bot.EDIT_SYNTAX in section
    assert "imagen=-" in section
    assert len(telegram_bot.help_text(True)) <= MAX_MESSAGE_LENGTH


# --- Conversation memory ---------------------------------------------------------------


def memory_rows(db, chat_id=CHAT_ID):
    db.expire_all()
    return [
        (row.role, row.content)
        for row in db.query(models.ConversationMessage)
        .filter_by(chat_id=chat_id)
        .order_by(models.ConversationMessage.id)
    ]


def drop_memory_table():
    models.ConversationMessage.__table__.drop(bind=test_engine)


def use_memory_factory(factory):
    app.dependency_overrides[conversation_memory.get_session_factory] = lambda: factory


class BrokenMemoryFactory:
    def __call__(self):
        raise RuntimeError("password=hunter2 host=db.internal")


def test_the_first_question_has_no_history_and_the_next_one_gets_the_turn(
    client, sender, use_assistant
):
    fake = use_assistant(FakeAssistant(answer="Hay 5 teclados."))

    post_update(client, text_update("¿Hay teclados?", update_id=1))
    post_update(client, text_update("¿Y cuánto cuestan?", update_id=2))

    first, second = fake.calls
    assert first["history"] == []
    assert second["history"] == [
        ConversationTurn("user", "¿Hay teclados?"),
        ConversationTurn("assistant", "Hay 5 teclados."),
    ]
    assert second["question"] == "¿Y cuánto cuestan?"


def test_a_successful_question_stores_exactly_one_user_and_one_assistant_message(
    client, sender, use_assistant, db_session
):
    use_assistant(FakeAssistant(answer="Hay 5 teclados."))

    post_update(client, text_update("  ¿Hay teclados?  "))

    assert memory_rows(db_session) == [
        ("user", "¿Hay teclados?"),
        ("assistant", "Hay 5 teclados."),
    ]


def test_the_reply_is_sent_to_the_chat_as_before(client, sender, use_assistant):
    use_assistant(FakeAssistant(answer="Hay 5 teclados."))

    post_update(client, text_update("¿Hay teclados?"))

    assert sender.sent == [(CHAT_ID, "Hay 5 teclados.")]


def test_the_history_sent_to_the_assistant_never_exceeds_ten_messages(
    client, sender, use_assistant, db_session
):
    fake = use_assistant(FakeAssistant(answer="ok"))

    for n in range(1, 9):
        post_update(client, text_update(f"q{n}", update_id=n))

    assert len(fake.calls[-1]["history"]) == conversation_memory.MAX_HISTORY_MESSAGES
    assert fake.calls[-1]["history"][0] == ConversationTurn("user", "q3")
    assert len(memory_rows(db_session)) == conversation_memory.MAX_HISTORY_MESSAGES


def test_a_chat_never_gets_the_history_of_another_chat(client, sender, use_assistant):
    fake = use_assistant(FakeAssistant(answer="Respuesta"))

    post_update(client, text_update("pregunta de A", chat_id=1, update_id=1))
    post_update(client, text_update("pregunta de B", chat_id=2, update_id=2))
    post_update(client, text_update("otra de A", chat_id=1, update_id=3))

    _, b_call, a_call = fake.calls
    assert b_call["history"] == []
    assert [turn.content for turn in a_call["history"]] == ["pregunta de A", "Respuesta"]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(AssistantUnavailable("outage"), id="unavailable"),
        pytest.param(AssistantQuotaExceeded("quota"), id="quota"),
        pytest.param(RuntimeError("boom"), id="unexpected"),
    ],
)
def test_an_assistant_failure_stores_nothing(
    client, sender, use_assistant, db_session, error
):
    use_assistant(FakeAssistant(error=error))

    post_update(client, text_update("¿Hay teclados?"))

    assert memory_rows(db_session) == []
    assert len(sender.sent) == 1  # The friendly error text only.


def test_a_missing_assistant_key_stores_nothing(client, sender, db_session):
    post_update(client, text_update("¿Hay teclados?"))

    assert memory_rows(db_session) == []


def test_a_reply_that_could_not_be_delivered_is_not_remembered(
    client, telegram_env, use_sender, use_assistant, db_session
):
    use_sender(FakeSender(error=TelegramSendError("Bot API returned HTTP 500")))
    use_assistant(FakeAssistant(answer="Hay 5."))

    response = post_update(client, text_update("¿Hay teclados?"))

    assert response.status_code == 200
    assert memory_rows(db_session) == []


@pytest.mark.parametrize(
    "command",
    [
        "/start",
        "/ayuda",
        "/id",
        "/productos",
        "/agregar Mouse; 10; 5",
        "/editar 1 precio=12",
        "/agregar mal",
        "/desconocido",
        "/olvidar",
        "x" * 501,
    ],
)
def test_commands_and_their_replies_are_never_stored(
    client, sender, assistant, admin, db_session, command
):
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10})

    response = post_update(client, text_update(command))

    assert response.status_code == 200
    assert memory_rows(db_session) == []
    assert assistant.calls == []


def test_a_redelivered_question_is_stored_once(client, sender, assistant, db_session):
    post_update(client, text_update("¿Hay teclados?", update_id=77))
    post_update(client, text_update("¿Hay teclados?", update_id=77))

    assert len(memory_rows(db_session)) == 2
    assert len(assistant.calls) == 1


# Failure isolation: the code can be deployed before the table exists.


def test_a_missing_memory_table_still_answers_the_question(
    client, sender, use_assistant, db_session
):
    fake = use_assistant(FakeAssistant(answer="Hay 5."))
    drop_memory_table()

    response = post_update(client, text_update("¿Hay teclados?"))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, "Hay 5.")]
    assert fake.calls[0]["history"] == []


def test_a_memory_read_failure_keeps_the_catalog_and_releases_the_connection(
    client, sender, use_assistant, request_sessions
):
    probe = use_assistant(TransactionProbeAssistant(request_sessions))
    client.post(PRODUCTS_URL, json={"name": "Mouse", "price": 10, "stock": 3})
    request_sessions.clear()
    drop_memory_table()

    post_update(client, text_update("¿Hay ratones?"))

    assert probe.in_transaction == [False]
    assert sender.sent == [(CHAT_ID, "ok")]


def test_a_memory_write_failure_still_sends_the_answer(
    client, sender, use_assistant, caplog
):
    use_assistant(FakeAssistant(answer="Hay 5."))
    use_memory_factory(BrokenMemoryFactory())

    with caplog.at_level(logging.WARNING):
        response = post_update(client, text_update("¿Hay teclados?"))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, "Hay 5.")]
    assert str(CHAT_ID) in caplog.text
    assert "RuntimeError" in caplog.text
    assert "hunter2" not in caplog.text


def test_memory_failures_never_log_message_contents(
    client, sender, use_assistant, caplog
):
    use_assistant(FakeAssistant(answer="secret answer"))
    drop_memory_table()

    with caplog.at_level(logging.WARNING):
        post_update(client, text_update("secret question"))

    assert "OperationalError" in caplog.text
    assert "secret" not in caplog.text


# /olvidar


def test_olvidar_clears_this_chat_and_says_how_many_messages_it_forgot(
    client, sender, assistant, db_session
):
    conversation_memory.remember_turn(db_session, CHAT_ID, "q1", "a1")
    conversation_memory.remember_turn(db_session, CHAT_ID, "q2", "a2")

    response = post_update(client, text_update("/olvidar"))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.forgotten_text(4))]
    assert "4 mensajes" in telegram_bot.forgotten_text(4)
    assert memory_rows(db_session) == []
    assert assistant.calls == []


def test_olvidar_uses_the_singular_for_one_message():
    assert "1 mensaje" in telegram_bot.forgotten_text(1)
    assert "mensajes" not in telegram_bot.forgotten_text(1)


def test_olvidar_with_nothing_stored_says_so(client, sender, assistant):
    post_update(client, text_update("/olvidar"))

    assert sender.sent == [(CHAT_ID, telegram_bot.NOTHING_TO_FORGET_TEXT)]


def test_olvidar_only_clears_the_chat_that_sent_it(client, sender, assistant, db_session):
    conversation_memory.remember_turn(db_session, 1, "mine", "mine")
    conversation_memory.remember_turn(db_session, 2, "yours", "yours")

    post_update(client, text_update("/olvidar", chat_id=1))

    assert memory_rows(db_session, 1) == []
    assert memory_rows(db_session, 2) == [("user", "yours"), ("assistant", "yours")]


@pytest.mark.parametrize("command", ["/OLVIDAR", "/olvidar@CatalogBot", "/olvidar ahora"])
def test_olvidar_accepts_the_bot_suffix_case_and_a_payload(
    client, sender, assistant, db_session, command
):
    conversation_memory.remember_turn(db_session, CHAT_ID, "q", "a")

    post_update(client, text_update(command))

    assert sender.sent == [(CHAT_ID, telegram_bot.forgotten_text(2))]


def test_olvidar_is_open_to_non_admins(client, sender, assistant, use_admins, db_session):
    use_admins(999)
    conversation_memory.remember_turn(db_session, CHAT_ID, "q", "a")

    post_update(client, text_update("/olvidar"))

    assert memory_rows(db_session) == []


def test_the_assistant_gets_no_history_after_olvidar(client, sender, use_assistant):
    fake = use_assistant(FakeAssistant(answer="ok"))
    post_update(client, text_update("antes", update_id=1))
    post_update(client, text_update("/olvidar", update_id=2))

    post_update(client, text_update("después", update_id=3))

    assert fake.calls[-1]["history"] == []


def test_olvidar_without_the_table_replies_with_the_unavailable_text(
    client, sender, assistant
):
    drop_memory_table()

    response = post_update(client, text_update("/olvidar"))

    assert response.status_code == 200
    assert sender.sent == [(CHAT_ID, telegram_bot.UNAVAILABLE_TEXT)]


def test_olvidar_leaves_no_session_in_a_transaction(
    client, sender, assistant, request_sessions
):
    request_sessions.clear()

    post_update(client, text_update("/olvidar"))

    assert [session.in_transaction() for session in request_sessions] == [False]


def test_olvidar_is_listed_in_the_help_text_for_everyone():
    assert "/olvidar" in telegram_bot.WELCOME_TEXT
    assert "/olvidar" in telegram_bot.help_text(True)


def test_olvidar_duplicate_delivery_replies_once(client, sender, assistant):
    post_update(client, text_update("/olvidar", update_id=9))
    post_update(client, text_update("/olvidar", update_id=9))

    assert len(sender.sent) == 1


def test_the_welcome_text_makes_no_claim_about_answering_in_other_languages():
    assert "idioma" not in telegram_bot.WELCOME_TEXT.lower()
