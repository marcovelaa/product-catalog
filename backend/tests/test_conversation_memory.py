"""Conversation memory tests. They use the in-memory SQLite test database only."""

import dataclasses
import logging
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

import conversation_memory
import models
from catalog_assistant import ConversationTurn
from conftest import TestingSessionLocal, test_engine
from conversation_memory import (
    MAX_HISTORY_MESSAGES,
    MAX_MESSAGE_CHARS,
    forget,
    read_history_safely,
    recent,
    remember_turn,
    remember_turn_safely,
)

CHAT_A = 111
CHAT_B = -222  # Group chat ids are negative.
SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "telegram_messages.sql"


def stored(db, chat_id):
    return [
        (row.role, row.content)
        for row in db.scalars(
            select(models.ConversationMessage)
            .where(models.ConversationMessage.chat_id == chat_id)
            .order_by(models.ConversationMessage.id)
        )
    ]


def drop_table():
    models.ConversationMessage.__table__.drop(bind=test_engine)


class BrokenFactory:
    """A session factory for a database that is down."""

    def __call__(self):
        raise RuntimeError("password=hunter2 host=db.internal")


# --- remember / recent ---------------------------------------------------------


def test_window_is_ten_messages():
    assert MAX_HISTORY_MESSAGES == 10


def test_recent_is_empty_for_a_chat_without_history(db_session):
    assert recent(db_session, CHAT_A) == ()


def test_remember_turn_stores_the_question_then_the_answer(db_session):
    remember_turn(db_session, CHAT_A, "¿Hay teclados?", "Sí, hay 5.")

    assert stored(db_session, CHAT_A) == [
        ("user", "¿Hay teclados?"),
        ("assistant", "Sí, hay 5."),
    ]


def test_recent_returns_oldest_first_as_immutable_turns(db_session):
    remember_turn(db_session, CHAT_A, "q1", "a1")
    remember_turn(db_session, CHAT_A, "q2", "a2")

    history = recent(db_session, CHAT_A)

    assert history == (
        ConversationTurn("user", "q1"),
        ConversationTurn("assistant", "a1"),
        ConversationTurn("user", "q2"),
        ConversationTurn("assistant", "a2"),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        history[0].content = "changed"


def test_recent_honours_a_smaller_limit_and_keeps_the_newest(db_session):
    remember_turn(db_session, CHAT_A, "q1", "a1")
    remember_turn(db_session, CHAT_A, "q2", "a2")

    assert recent(db_session, CHAT_A, limit=2) == (
        ConversationTurn("user", "q2"),
        ConversationTurn("assistant", "a2"),
    )


def test_recent_never_starts_with_an_assistant_message(db_session):
    # An odd window (or an interleaved write) must not open on the model's turn.
    remember_turn(db_session, CHAT_A, "q1", "a1")
    remember_turn(db_session, CHAT_A, "q2", "a2")

    assert [turn.content for turn in recent(db_session, CHAT_A, limit=3)] == ["q2", "a2"]


def test_chats_never_see_each_others_messages(db_session):
    remember_turn(db_session, CHAT_A, "question of A", "answer for A")
    remember_turn(db_session, CHAT_B, "question of B", "answer for B")

    assert [turn.content for turn in recent(db_session, CHAT_A)] == [
        "question of A",
        "answer for A",
    ]
    assert [turn.content for turn in recent(db_session, CHAT_B)] == [
        "question of B",
        "answer for B",
    ]


def test_only_the_last_ten_messages_of_a_chat_are_kept(db_session):
    for n in range(1, 8):  # 7 turns = 14 messages
        remember_turn(db_session, CHAT_A, f"q{n}", f"a{n}")

    rows = stored(db_session, CHAT_A)

    assert len(rows) == MAX_HISTORY_MESSAGES
    assert rows[0] == ("user", "q3")
    assert rows[-1] == ("assistant", "a7")
    assert [turn.content for turn in recent(db_session, CHAT_A)] == [
        content for _, content in rows
    ]


def test_pruning_one_chat_leaves_the_others_untouched(db_session):
    remember_turn(db_session, CHAT_B, "kept q", "kept a")
    for n in range(1, 8):
        remember_turn(db_session, CHAT_A, f"q{n}", f"a{n}")

    assert stored(db_session, CHAT_B) == [("user", "kept q"), ("assistant", "kept a")]


def test_long_messages_are_truncated_before_they_are_stored(db_session):
    remember_turn(db_session, CHAT_A, "q" * 5000, "a" * 5000)

    [(_, question), (_, answer)] = stored(db_session, CHAT_A)

    assert len(question) == len(answer) == MAX_MESSAGE_CHARS
    assert MAX_MESSAGE_CHARS == 1000


def test_messages_at_the_cap_are_stored_whole(db_session):
    remember_turn(db_session, CHAT_A, "q" * MAX_MESSAGE_CHARS, "a")

    assert stored(db_session, CHAT_A)[0][1] == "q" * MAX_MESSAGE_CHARS


# --- forget --------------------------------------------------------------------


def test_forget_deletes_one_chat_and_returns_how_many_messages_it_removed(db_session):
    remember_turn(db_session, CHAT_A, "q1", "a1")
    remember_turn(db_session, CHAT_A, "q2", "a2")
    remember_turn(db_session, CHAT_B, "other", "chat")

    assert forget(db_session, CHAT_A) == 4
    assert stored(db_session, CHAT_A) == []
    assert stored(db_session, CHAT_B) == [("user", "other"), ("assistant", "chat")]


def test_forget_returns_zero_when_there_is_nothing_to_forget(db_session):
    assert forget(db_session, CHAT_A) == 0


def test_memory_works_again_after_forgetting(db_session):
    remember_turn(db_session, CHAT_A, "old q", "old a")
    forget(db_session, CHAT_A)
    remember_turn(db_session, CHAT_A, "new q", "new a")

    assert [turn.content for turn in recent(db_session, CHAT_A)] == ["new q", "new a"]


# --- failure isolation ---------------------------------------------------------


def test_read_history_safely_returns_the_history(db_session):
    remember_turn(db_session, CHAT_A, "q", "a")

    assert [t.content for t in read_history_safely(db_session, CHAT_A)] == ["q", "a"]


def test_read_history_safely_degrades_to_no_memory_without_the_table(
    db_session, caplog
):
    drop_table()

    with caplog.at_level(logging.WARNING):
        assert read_history_safely(db_session, CHAT_A) == ()

    assert not db_session.in_transaction()
    assert str(CHAT_A) in caplog.text and "OperationalError" in caplog.text
    assert "telegram_messages" not in caplog.text  # No SQL or detail in the log.


def test_read_history_safely_ends_its_transaction(db_session):
    read_history_safely(db_session, CHAT_A)

    assert not db_session.in_transaction()


def test_remember_turn_safely_saves_with_its_own_session(db_session):
    remember_turn_safely(TestingSessionLocal, CHAT_A, "q", "a")

    assert stored(db_session, CHAT_A) == [("user", "q"), ("assistant", "a")]


def test_remember_turn_safely_swallows_a_missing_table_and_logs_class_only(caplog):
    drop_table()

    with caplog.at_level(logging.WARNING):
        remember_turn_safely(TestingSessionLocal, CHAT_A, "secret question", "secret answer")

    assert str(CHAT_A) in caplog.text and "OperationalError" in caplog.text
    assert "secret" not in caplog.text


def test_remember_turn_safely_swallows_a_factory_failure_without_leaking_details(
    caplog,
):
    with caplog.at_level(logging.WARNING):
        remember_turn_safely(BrokenFactory(), CHAT_A, "q", "a")

    assert "RuntimeError" in caplog.text
    assert "hunter2" not in caplog.text


def test_remember_turn_safely_closes_its_session():
    closed = []

    class RecordingSession(Session):
        def close(self):
            closed.append(True)
            super().close()

    remember_turn_safely(
        lambda: RecordingSession(bind=test_engine), CHAT_A, "q", "a"
    )

    assert closed == [True]


def test_the_default_session_factory_is_the_applications_sessionmaker():
    from database import SessionLocal

    assert conversation_memory.get_session_factory() is SessionLocal


# --- The SQL that is run once in Supabase -----------------------------------------


def sql_statements():
    lines = [
        line for line in SQL_FILE.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    ]
    return " ".join(" ".join(lines).split()).lower()


def test_the_sql_creates_the_table_idempotently_with_the_orm_columns():
    sql = sql_statements()

    assert "create table if not exists telegram_messages" in sql
    assert "id bigint generated by default as identity primary key" in sql
    assert "chat_id bigint not null" in sql
    assert "role text not null check (role in ('user', 'assistant'))" in sql
    assert "content text not null" in sql
    assert "created_at timestamptz not null default now()" in sql
    assert "create index if not exists" in sql and "(chat_id, id)" in sql
    assert {c.name for c in models.ConversationMessage.__table__.columns} == {
        "id", "chat_id", "role", "content", "created_at",
    }


def test_the_sql_enables_row_level_security_and_defines_no_policy():
    sql = sql_statements()

    assert "alter table telegram_messages enable row level security;" in sql
    assert "policy" not in sql  # No policy: the public Data API exposes nothing.
    assert "grant" not in sql


def test_the_orm_table_matches_the_sql_table_name():
    assert models.ConversationMessage.__tablename__ == "telegram_messages"
    with TestingSessionLocal() as db:
        assert db.execute(text("select count(*) from telegram_messages")).scalar() == 0
