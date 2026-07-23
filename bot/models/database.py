import logging
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from bot.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("player_tag", name="uq_users_player_tag"),)

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
    app_settings: Mapped["UserSettings | None"] = relationship(
        back_populates="user", uselist=False
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    theme: Mapped[str] = mapped_column(String(10), default="dark")
    language: Mapped[str] = mapped_column(String(5), default="ru")
    notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    haptic_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship(back_populates="app_settings")


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
    __table_args__ = (
        UniqueConstraint("player_tag", "battle_time", name="uq_battle_cache_player_time"),
    )

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

        result = await conn.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('user_settings') WHERE name='haptic_enabled'")
        )
        if result.scalar_one_or_none() == 0:
            await conn.execute(
                text("ALTER TABLE user_settings ADD COLUMN haptic_enabled BOOLEAN DEFAULT 1 NOT NULL")
            )
            logger.info("Added 'haptic_enabled' column to user_settings table")

    await _migrate_battle_cache_dedup()
    await _migrate_users_player_tag_unique()


async def _migrate_users_player_tag_unique() -> None:
    """Normalize player_tag values and add unique index when no duplicates exist."""
    from bot.services.clash_api import normalize_tag

    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(User).where(User.player_tag.is_not(None)))
        rows = result.scalars().all()
        normalized = 0
        for row in rows:
            if not row.player_tag:
                continue
            canon = normalize_tag(row.player_tag)
            if canon != row.player_tag:
                row.player_tag = canon
                normalized += 1
        if normalized:
            await session.commit()
            logger.info("Normalized %d users.player_tag values", normalized)

    async with engine.begin() as conn:
        index_exists = await conn.execute(
            text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='index' AND name='uq_users_player_tag'"
            )
        )
        if index_exists.scalar_one():
            return

        dupes = await conn.execute(
            text(
                "SELECT player_tag, COUNT(*) AS cnt "
                "FROM users "
                "WHERE player_tag IS NOT NULL "
                "GROUP BY player_tag "
                "HAVING cnt > 1"
            )
        )
        dupe_rows = dupes.fetchall()
        if dupe_rows:
            logger.warning(
                "users has %d duplicate player_tag groups; "
                "unique index not created — resolve manually before enforcing uniqueness",
                len(dupe_rows),
            )
            for player_tag, cnt in dupe_rows[:10]:
                ids = await conn.execute(
                    text(
                        "SELECT id, telegram_id FROM users "
                        "WHERE player_tag = :tag ORDER BY id"
                    ),
                    {"tag": player_tag},
                )
                users = ids.fetchall()
                logger.warning(
                    "  duplicate player_tag=%s count=%d users=%s",
                    player_tag,
                    cnt,
                    [(u[0], u[1]) for u in users],
                )
            return

        await conn.execute(
            text("CREATE UNIQUE INDEX uq_users_player_tag ON users (player_tag)")
        )
        logger.info("Created unique index uq_users_player_tag on users(player_tag)")


async def _migrate_battle_cache_dedup() -> None:
    """Normalize battle_time values and add unique index when DB has no duplicates."""
    from bot.services.battle_time import normalize_battle_time

    async with async_session() as session:
        from sqlalchemy import select

        from bot.models.database import BattleCache

        result = await session.execute(select(BattleCache))
        rows = result.scalars().all()
        normalized = 0
        for row in rows:
            canon = normalize_battle_time(row.battle_time)
            if canon and canon != row.battle_time:
                row.battle_time = canon
                normalized += 1
        if normalized:
            await session.commit()
            logger.info("Normalized %d battle_cache.battle_time values", normalized)

    async with engine.begin() as conn:
        index_exists = await conn.execute(
            text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='index' AND name='uq_battle_cache_player_time'"
            )
        )
        if index_exists.scalar_one():
            return

        dupes = await conn.execute(
            text(
                "SELECT player_tag, battle_time, COUNT(*) AS cnt "
                "FROM battle_cache "
                "GROUP BY player_tag, battle_time "
                "HAVING cnt > 1"
            )
        )
        dupe_rows = dupes.fetchall()
        if dupe_rows:
            logger.warning(
                "battle_cache has %d duplicate (player_tag, battle_time) groups; "
                "unique index not created — review manually before dedup cleanup",
                len(dupe_rows),
            )
            for player_tag, battle_time, cnt in dupe_rows[:10]:
                logger.warning(
                    "  duplicate battle_cache: tag=%s time=%s count=%d",
                    player_tag,
                    battle_time,
                    cnt,
                )
            return

        await conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_battle_cache_player_time "
                "ON battle_cache (player_tag, battle_time)"
            )
        )
        logger.info("Created unique index uq_battle_cache_player_time on battle_cache")
