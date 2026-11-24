import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Load variables from backend/.env for local development.
# Variables that are already set (Render env vars, tests) are never overridden.
load_dotenv()


def get_database_url() -> str:
    """Return DATABASE_URL or fail fast with an actionable message."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Locally, copy .env.example to .env and paste your "
            "Supabase Session pooler connection string "
            "(postgresql+psycopg2://postgres.<PROJECT_REF>:<PASSWORD>@aws-0-<REGION>"
            ".pooler.supabase.com:5432/postgres). On Render, add DATABASE_URL under "
            "Environment."
        )
    return _pin_postgres_driver(url)


# SQLAlchemy 2.1 maps a driverless postgresql:// URL to psycopg 3, but this project
# installs psycopg2. Supabase hands out driverless URLs, so pin the driver here.
_DRIVERLESS_POSTGRES_SCHEMES = ("postgresql://", "postgres://")


def _pin_postgres_driver(url: str) -> str:
    for scheme in _DRIVERLESS_POSTGRES_SCHEMES:
        if url.startswith(scheme):
            return "postgresql+psycopg2://" + url[len(scheme):]
    return url


# pool_pre_ping discards connections that the Supabase pooler closed while idle.
engine = create_engine(get_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
