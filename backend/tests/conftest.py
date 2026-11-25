import os

# Force test settings before any app module is imported.
# load_dotenv() never overrides variables that are already set (even to an empty
# string), so a real .env file can never leak Supabase credentials or a Gemini
# API key into the test suite. Tests must never reach the network.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173"
os.environ["GEMINI_API_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_WEBHOOK_SECRET"] = ""
os.environ["TELEGRAM_ADMIN_IDS"] = ""
os.environ["SLACK_WEBHOOK_URL"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import catalog_assistant  # noqa: E402
import telegram_bot  # noqa: E402
import models  # noqa: E402,F401  (registers the Product table on Base.metadata)
from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def fresh_schema():
    """Give every test an empty products table."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def isolated_assistant():
    """Reset the cached Gemini adapter and any assistant override per test."""
    catalog_assistant.gemini_assistant_for.cache_clear()
    yield
    catalog_assistant.gemini_assistant_for.cache_clear()
    app.dependency_overrides.pop(catalog_assistant.get_catalog_assistant, None)


@pytest.fixture(autouse=True)
def recent_updates():
    """Give every test a fresh update_id record so no state leaks between tests."""
    recent = telegram_bot.RecentUpdates()
    app.dependency_overrides[telegram_bot.get_recent_updates] = lambda: recent
    yield recent
    app.dependency_overrides.pop(telegram_bot.get_recent_updates, None)


@pytest.fixture
def request_sessions():
    """Record every DB session handed to a request, to inspect its state."""
    sessions = []

    def recording_get_db():
        db = TestingSessionLocal()
        sessions.append(db)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = recording_get_db
    yield sessions
    app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
