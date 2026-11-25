"""Short conversation memory for the Telegram bot, kept in the `telegram_messages` table.

Each chat (keyed by its Telegram chat id) keeps only its last MAX_HISTORY_MESSAGES
messages, each cut to MAX_MESSAGE_CHARS, so neither the table nor the prompt can
grow without bound. The history is given to the model as earlier conversation
turns, never merged into the system instruction.

Memory is a convenience, not a requirement: every `*_safely` helper degrades to
"no memory" on any failure (for example the table was not created yet), so a
memory problem can never stop a question from being answered.
"""

import logging
from collections.abc import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import models
from catalog_assistant import MAX_HISTORY_MESSAGES, ConversationTurn
from database import SessionLocal

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_HISTORY_MESSAGES",
    "MAX_MESSAGE_CHARS",
    "forget",
    "get_session_factory",
    "read_history_safely",
    "recent",
    "remember_turn",
    "remember_turn_safely",
]

MAX_MESSAGE_CHARS = 1000
USER = "user"
ASSISTANT = "assistant"

SessionFactory = Callable[[], Session]


def get_session_factory() -> SessionFactory:
    """FastAPI dependency: where background tasks open their own short-lived sessions."""
    return SessionLocal


def recent(
    db: Session, chat_id: int, limit: int = MAX_HISTORY_MESSAGES
) -> tuple[ConversationTurn, ...]:
    """The newest `limit` messages of a chat, oldest first; never opens on a model turn."""
    rows = db.execute(
        select(models.ConversationMessage.role, models.ConversationMessage.content)
        .where(models.ConversationMessage.chat_id == chat_id)
        .order_by(models.ConversationMessage.id.desc())
        .limit(limit)
    ).all()
    turns = [ConversationTurn(role=row.role, content=row.content) for row in reversed(rows)]
    while turns and turns[0].role != USER:
        turns.pop(0)
    return tuple(turns)


def remember_turn(db: Session, chat_id: int, question: str, answer: str) -> None:
    """Save a question and its answer, then drop the chat's messages beyond the window."""
    db.add_all(
        [
            models.ConversationMessage(
                chat_id=chat_id, role=USER, content=question[:MAX_MESSAGE_CHARS]
            ),
            models.ConversationMessage(
                chat_id=chat_id, role=ASSISTANT, content=answer[:MAX_MESSAGE_CHARS]
            ),
        ]
    )
    db.flush()  # Assigns the ids that the pruning below orders by.
    keep = (
        select(models.ConversationMessage.id)
        .where(models.ConversationMessage.chat_id == chat_id)
        .order_by(models.ConversationMessage.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
    )
    db.execute(
        delete(models.ConversationMessage).where(
            models.ConversationMessage.chat_id == chat_id,
            models.ConversationMessage.id.not_in(keep),
        )
    )
    db.commit()


def forget(db: Session, chat_id: int) -> int:
    """Delete every stored message of one chat; returns how many were removed."""
    result = db.execute(
        delete(models.ConversationMessage).where(
            models.ConversationMessage.chat_id == chat_id
        )
    )
    db.commit()
    return result.rowcount


def read_history_safely(db: Session, chat_id: int) -> tuple[ConversationTurn, ...]:
    """`recent`, but any failure means "no memory"; the session never stays in a transaction."""
    try:
        return recent(db, chat_id)
    except Exception as error:
        _log_failure("read", chat_id, error)
        return ()
    finally:
        db.rollback()


def remember_turn_safely(
    session_factory: SessionFactory, chat_id: int, question: str, answer: str
) -> None:
    """Save a turn with a session of its own; a failure is logged and swallowed.

    Meant for a background task: the request's session is already closed by then.
    """
    db = None
    try:
        db = session_factory()
        remember_turn(db, chat_id, question, answer)
    except Exception as error:
        _log_failure("write", chat_id, error)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as error:
                _log_failure("close", chat_id, error)


def _log_failure(action: str, chat_id: int, error: Exception) -> None:
    # The class only: an error message can carry SQL, hosts or message contents.
    logger.warning(
        "Conversation memory %s failed (chat_id=%s, error=%s)",
        action, chat_id, type(error).__name__,
    )
