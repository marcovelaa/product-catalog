"""Slack "product created" alert tests. They never reach the network: the notifier
is always faked, or the adapter runs on httpx.MockTransport."""

import json
import logging

import httpx
import pytest

from main import app
from slack_alerts import (
    MAX_NAME_LENGTH,
    SEND_TIMEOUT_SECONDS,
    HttpxSlackNotifier,
    SlackSendError,
    format_product_created,
    get_slack_notifier,
)

PRODUCTS_URL = "/api/v1/products"
WEBHOOK_URL = "https://hooks.slack.com/services/T000/B000/SECRET-webhook-token"
NEW_PRODUCT = {"name": "Mechanical Keyboard", "price": 49.5, "stock": 12}


# --- Fakes and helpers -------------------------------------------------------


class FakeNotifier:
    """In-memory SlackNotifier that records every message."""

    def __init__(self, error=None):
        self._error = error
        self.sent = []

    def post_message(self, text):
        self.sent.append(text)
        if self._error is not None:
            raise self._error


class TransactionProbeNotifier(FakeNotifier):
    """Captures the request's DB session state at the moment post_message runs."""

    def __init__(self, sessions):
        super().__init__()
        self._sessions = sessions
        self.in_transaction = None

    def post_message(self, text):
        self.in_transaction = [session.in_transaction() for session in self._sessions]
        super().post_message(text)


@pytest.fixture
def use_notifier():
    def install(notifier):
        app.dependency_overrides[get_slack_notifier] = lambda: notifier
        return notifier

    yield install
    app.dependency_overrides.pop(get_slack_notifier, None)


@pytest.fixture
def notifier(use_notifier):
    return use_notifier(FakeNotifier())


def create(client, **overrides):
    return client.post(PRODUCTS_URL, json={**NEW_PRODUCT, **overrides})


# --- Triggering --------------------------------------------------------------


def test_creating_a_product_sends_exactly_one_alert(client, notifier):
    response = create(client)

    assert response.status_code == 201
    product_id = response.json()["id"]
    assert notifier.sent == [
        f"New product: Mechanical Keyboard (id {product_id}) - price Bs 49.50, stock 12"
    ]


def test_price_is_formatted_with_two_decimals(client, notifier):
    create(client, price=10)

    assert "price Bs 10.00," in notifier.sent[0]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"name": "", "price": 1, "stock": 1}, id="empty-name"),
        pytest.param({"name": "Ok", "price": -1, "stock": 1}, id="negative-price"),
        pytest.param({"price": 1, "stock": 1}, id="missing-name"),
    ],
)
def test_invalid_product_sends_no_alert(client, notifier, payload):
    response = client.post(PRODUCTS_URL, json=payload)

    assert response.status_code == 422
    assert notifier.sent == []


def test_listing_products_sends_no_alert(client, notifier):
    assert client.get(PRODUCTS_URL).status_code == 200
    assert notifier.sent == []


# --- Disabled and failing notifier -------------------------------------------


def test_without_a_webhook_url_alerts_are_disabled(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no request may be sent when Slack is not configured")

    monkeypatch.setattr(httpx.Client, "post", forbidden)

    response = create(client)

    assert get_slack_notifier() is None
    assert response.status_code == 201
    assert response.json()["name"] == NEW_PRODUCT["name"]


@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_webhook_url_counts_as_not_configured(monkeypatch, raw):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", raw)

    assert get_slack_notifier() is None


def test_configured_webhook_url_builds_the_http_adapter(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", f"  {WEBHOOK_URL}  ")

    assert isinstance(get_slack_notifier(), HttpxSlackNotifier)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(httpx.ConnectTimeout("timed out"), id="timeout"),
        pytest.param(httpx.ConnectError("network is unreachable"), id="network"),
        pytest.param(SlackSendError("Slack webhook returned HTTP 500"), id="non-2xx"),
        pytest.param(RuntimeError("boom"), id="unexpected"),
    ],
)
def test_notifier_failure_never_changes_the_created_response(
    client, use_notifier, caplog, error
):
    failing = use_notifier(FakeNotifier(error=error))

    with caplog.at_level(logging.WARNING, logger="slack_alerts"):
        response = create(client)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == NEW_PRODUCT["name"]
    assert body["price"] == NEW_PRODUCT["price"]
    assert body["stock"] == NEW_PRODUCT["stock"]
    assert len(failing.sent) == 1
    assert type(error).__name__ in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    # The product really was committed.
    assert [row["id"] for row in client.get(PRODUCTS_URL).json()] == [body["id"]]


def test_alert_is_sent_after_the_db_session_released_its_transaction(
    client, use_notifier, request_sessions
):
    probe = use_notifier(TransactionProbeNotifier(request_sessions))

    response = create(client)

    assert response.status_code == 201
    assert probe.in_transaction == [False]


# --- Message content ---------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected_name"),
    [
        pytest.param("<!channel>", "&lt;!channel&gt;", id="channel-mention"),
        pytest.param("<!here> now", "&lt;!here&gt; now", id="here-mention"),
        pytest.param("<@U123>", "&lt;@U123&gt;", id="user-mention"),
        pytest.param(
            "<https://evil.test|click me>",
            "&lt;https://evil.test|click me&gt;",
            id="link",
        ),
        pytest.param("Tom & Jerry", "Tom &amp; Jerry", id="ampersand"),
        pytest.param("&lt;already&gt;", "&amp;lt;already&amp;gt;", id="no-double-decoding"),
        pytest.param("line one\nline two\r\n\tline three", "line one line two line three", id="newlines"),
    ],
)
def test_product_name_is_neutralized_for_slack_mrkdwn(client, notifier, name, expected_name):
    response = create(client, name=name)

    assert response.status_code == 201
    assert notifier.sent == [
        f"New product: {expected_name} (id {response.json()['id']}) - price Bs 49.50, stock 12"
    ]
    assert "<" not in notifier.sent[0]
    assert ">" not in notifier.sent[0]


def test_very_long_name_is_capped_with_an_ellipsis(client, notifier):
    response = create(client, name="x" * 200)

    assert response.status_code == 201
    message = notifier.sent[0]
    assert "x" * MAX_NAME_LENGTH + "..." in message
    assert "x" * (MAX_NAME_LENGTH + 1) not in message


def test_name_at_the_cap_is_not_truncated():
    message = format_product_created("y" * MAX_NAME_LENGTH, 1, 2.0, 3)

    assert "y" * MAX_NAME_LENGTH + " (id 1)" in message
    assert "..." not in message


def test_cap_never_splits_an_escaped_entity():
    message = format_product_created("&" * 150, 1, 2.0, 3)

    assert "&amp;" * MAX_NAME_LENGTH + "..." in message
    assert "&am..." not in message


# --- HttpxSlackNotifier (adapter) --------------------------------------------


def recording_transport(status_code=200):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status_code, text="ok")

    return httpx.MockTransport(handler), requests


def test_adapter_posts_json_text_to_the_webhook_url():
    transport, requests = recording_transport()

    HttpxSlackNotifier(WEBHOOK_URL, transport=transport).post_message("hello <world>")

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == WEBHOOK_URL
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {"text": "hello <world>"}


def test_adapter_uses_a_short_timeout_without_retries(monkeypatch):
    seen = {}
    real_client = httpx.Client

    def spying_client(*args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        seen["kwargs"] = kwargs
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", spying_client)
    transport, _ = recording_transport()

    HttpxSlackNotifier(WEBHOOK_URL, transport=transport).post_message("hi")

    assert SEND_TIMEOUT_SECONDS == 3.0
    assert httpx.Timeout(seen["timeout"]) == httpx.Timeout(3.0)
    assert "retries" not in seen["kwargs"]


def test_adapter_makes_a_single_attempt_on_server_error():
    transport, requests = recording_transport(status_code=500)

    with pytest.raises(SlackSendError):
        HttpxSlackNotifier(WEBHOOK_URL, transport=transport).post_message("hi")

    assert len(requests) == 1


@pytest.mark.parametrize("status_code", [400, 403, 404, 429, 500, 503])
def test_adapter_raises_on_non_2xx_without_leaking_the_url(status_code):
    transport, _ = recording_transport(status_code=status_code)
    notifier = HttpxSlackNotifier(WEBHOOK_URL, transport=transport)

    with pytest.raises(SlackSendError) as excinfo:
        notifier.post_message("hi")

    assert str(status_code) in str(excinfo.value)
    assert "SECRET-webhook-token" not in str(excinfo.value)
    assert "hooks.slack.com" not in str(excinfo.value)
    assert WEBHOOK_URL not in repr(notifier)
    assert "SECRET-webhook-token" not in repr(notifier)


def test_real_adapter_failure_never_logs_the_webhook_url(client, use_notifier, caplog):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    use_notifier(HttpxSlackNotifier(WEBHOOK_URL, transport=httpx.MockTransport(refuse)))

    with caplog.at_level(logging.DEBUG):
        response = create(client)

    assert response.status_code == 201
    assert "ConnectError" in caplog.text
    assert WEBHOOK_URL not in caplog.text
    assert "SECRET-webhook-token" not in caplog.text
    assert "hooks.slack.com" not in caplog.text


def test_real_adapter_non_2xx_never_logs_the_webhook_url(client, use_notifier, caplog):
    transport, _ = recording_transport(status_code=404)
    use_notifier(HttpxSlackNotifier(WEBHOOK_URL, transport=transport))

    with caplog.at_level(logging.DEBUG):
        response = create(client)

    assert response.status_code == 201
    assert "SlackSendError" in caplog.text
    assert "SECRET-webhook-token" not in caplog.text
    assert "hooks.slack.com" not in caplog.text


def test_httpx_request_logging_is_kept_below_info():
    assert logging.getLogger("httpx").level >= logging.WARNING
