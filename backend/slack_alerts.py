"""Slack alert for newly created products (Incoming Webhook, fire and forget).

Ports and adapters:
- Port: `SlackNotifier`, the only thing the product route depends on to alert.
- Adapter: `HttpxSlackNotifier`, which posts `{"text": ...}` to the webhook URL.

The alert is optional and must never affect the API: it is sent from a background
task after the HTTP response, and every failure is logged and swallowed. The
webhook URL is a secret (anyone holding it can post to the channel), so it is
never logged and never part of an exception message or a repr.
"""

import logging
import os
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and a webhook URL is the secret itself.
logging.getLogger("httpx").setLevel(logging.WARNING)

SEND_TIMEOUT_SECONDS = 3.0  # Applied to connect, read, write and pool waits.
MAX_NAME_LENGTH = 100


# --- Message ---------------------------------------------------------------------


def neutralize_mrkdwn(text: str) -> str:
    """Make user-submitted text inert for Slack mrkdwn.

    Slack turns `<...>` into mentions (`<!channel>`, `<@U123>`) and links
    (`<https://evil|label>`); escaping `&`, `<` and `>` is what Slack documents
    to prevent that. Whitespace runs, newlines included, collapse to one space.
    """
    collapsed = " ".join(text.split())
    return collapsed.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_product_created(name: str, product_id: int, price: float, stock: int) -> str:
    # Cap before escaping so the cut can never split an `&amp;` style entity.
    collapsed = " ".join(name.split())
    if len(collapsed) > MAX_NAME_LENGTH:
        shown = neutralize_mrkdwn(collapsed[:MAX_NAME_LENGTH]) + "..."
    else:
        shown = neutralize_mrkdwn(collapsed)
    return f"New product: {shown} (id {product_id}) - price {price:.2f}, stock {stock}"


# --- Port and adapter --------------------------------------------------------------


class SlackNotifier(Protocol):
    def post_message(self, text: str) -> None: ...


class SlackSendError(Exception):
    """Slack rejected a message. The message never includes the webhook URL."""


class HttpxSlackNotifier:
    """SlackNotifier backed by a Slack Incoming Webhook."""

    def __init__(self, webhook_url: str, transport: httpx.BaseTransport | None = None):
        self._url = webhook_url
        self._transport = transport

    def __repr__(self) -> str:
        return "HttpxSlackNotifier(<redacted>)"

    def post_message(self, text: str) -> None:
        # One attempt, no retries: a lost alert is better than a delayed duplicate.
        with httpx.Client(timeout=SEND_TIMEOUT_SECONDS, transport=self._transport) as client:
            response = client.post(self._url, json={"text": text})
        if response.is_error:
            # Not raise_for_status(): its message would include the URL, and the secret.
            raise SlackSendError(f"Slack webhook returned HTTP {response.status_code}")


def get_slack_notifier() -> SlackNotifier | None:
    """Return the webhook adapter, or None when SLACK_WEBHOOK_URL is empty or missing."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return None
    return HttpxSlackNotifier(webhook_url)


# --- Background job ----------------------------------------------------------------


def send_safely(notifier: SlackNotifier | None, text: str) -> None:
    """Send an alert; a failure is logged and swallowed, never raised."""
    if notifier is None:
        return
    try:
        notifier.post_message(text)
    except Exception as error:
        # Log the class only: httpx error messages can contain the request URL.
        logger.warning("Slack alert failed (error=%s)", type(error).__name__)
