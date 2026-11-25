from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Product(Base):
    """ORM mapping of the `products` table defined in sql/schema.sql."""

    __tablename__ = "products"

    # BIGINT in Postgres; INTEGER on SQLite so tests get rowid autoincrement.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    stock: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConversationMessage(Base):
    """ORM mapping of the `telegram_messages` table (sql/telegram_messages.sql).

    One row per message of a Telegram chat's recent conversation, keyed by chat id.
    """

    __tablename__ = "telegram_messages"
    __table_args__ = (
        CheckConstraint("role in ('user', 'assistant')", name="telegram_messages_role_check"),
        Index("telegram_messages_chat_id_id_idx", "chat_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    # Telegram chat ids exceed 32 bits (and are negative for groups).
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
