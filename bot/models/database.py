import logging
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from bot.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    player_tag: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    player_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    arena_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trophies: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    subscription: Mapped["Subscription | None"] = relationship(
        back_populates="user", uselist=False
    )
    preferences: Mapped[list["CardPreference"]] = relationship(back_populates="user")
    favorite_decks: Mapped[list["FavoriteDeck"]] = relationship(back_populates="user")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user: Mapped["User"] = relationship(back_populates="subscription")


class CardPreference(Base):
    __tablename__ = "card_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    card_name: Mapped[str] = mapped_column(String(50))
    play_count: Mapped[int] = mapped_column(Integer, default=1)

    user: Mapped["User"] = relationship(back_populates="preferences")


class BattleCache(Base):
    __tablename__ = "battle_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    battle_time: Mapped[str] = mapped_column(String(30))
    result: Mapped[str] = mapped_column(String(10))
    user_deck: Mapped[str] = mapped_column(Text)
    opponent_deck: Mapped[str] = mapped_column(Text)
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)


class FavoriteDeck(Base):
    __tablename__ = "favorite_decks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    deck_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship(back_populates="favorite_decks")


engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('users') WHERE name='trophies'")
        )
        count = result.scalar_one_or_none()
        if count == 0:
            await conn.execute(text("ALTER TABLE users ADD COLUMN trophies INTEGER"))
            logger = logging.getLogger(__name__)
            logger.info("Added 'trophies' column to users table")
