import logging
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
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
    tracked_mine_decks: Mapped[list["TrackedMineDeck"]] = relationship(back_populates="user")
    app_settings: Mapped["UserSettings | None"] = relationship(
        back_populates="user", uselist=False
    )
    weekly_digests: Mapped[list["WeeklyDigestSent"]] = relationship(back_populates="user")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    theme: Mapped[str] = mapped_column(String(10), default="dark")
    language: Mapped[str] = mapped_column(String(5), default="ru")
    notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    haptic_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    haptic_intensity: Mapped[str] = mapped_column(String(10), default="standard")
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
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    user: Mapped["User"] = relationship(back_populates="subscription")


class ProPayment(Base):
    """Immutable Ghosteek Pro payment audit trail (Telegram Stars / XTR)."""

    __tablename__ = "pro_payments"
    __table_args__ = (
        UniqueConstraint("telegram_payment_charge_id", name="uq_pro_payments_charge"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    plan_id: Mapped[str] = mapped_column(String(32))
    stars: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="XTR")
    telegram_payment_charge_id: Mapped[str] = mapped_column(String(128))
    provider_payment_charge_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    invoice_payload: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


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
    # JSON of parsed cards (name, evolution_level, is_hero, …) — survives name-only CSV
    user_deck_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    opponent_name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    opponent_tag: Mapped[str] = mapped_column(String(20), default="", server_default="")
    trophy_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


class TrackedMineDeck(Base):
    """Постоянный слот «Мои колоды» (до 10): не исчезает после ротации battlelog."""

    __tablename__ = "tracked_mine_decks"
    __table_args__ = (
        UniqueConstraint("user_id", "deck_key", name="uq_tracked_mine_deck_user_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    deck_key: Mapped[str] = mapped_column(Text)  # sorted names joined by |
    cards_csv: Mapped[str] = mapped_column(Text, default="")  # display order
    # JSON list of parsed cards (evo/hero) — survives battlelog rotation / name-only cache
    cards_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    last_seen: Mapped[str] = mapped_column(String(30), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship(back_populates="tracked_mine_decks")


class WeeklyDigestSent(Base):
    __tablename__ = "weekly_digest_sent"
    __table_args__ = (UniqueConstraint("user_id", "week_key", name="uq_weekly_digest_user_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    week_key: Mapped[str] = mapped_column(String(16))
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship(back_populates="weekly_digests")


class ProReminderSent(Base):
    """Idempotent Ghosteek Pro expiry / trial reminders."""

    __tablename__ = "pro_reminder_sent"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "period_key", name="uq_pro_reminder_user_kind_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    period_key: Mapped[str] = mapped_column(String(32))
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MetaBattleObservation(Base):
    """One unique ladder battle observation from a scanned player's battlelog."""

    __tablename__ = "meta_battle_observations"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_meta_obs_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(120), index=True)
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    opponent_tag: Mapped[str] = mapped_column(String(20), default="", server_default="")
    battle_time: Mapped[str] = mapped_column(String(30))
    mode: Mapped[str] = mapped_column(String(16), index=True)  # league | trophies
    trophy_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deck_hash: Mapped[str] = mapped_column(String(200), index=True)
    cards_csv: Mapped[str] = mapped_column(Text, default="")
    cards_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    result: Mapped[str] = mapped_column(String(8))  # win | loss | draw
    source: Mapped[str] = mapped_column(String(32), default="cr_api", server_default="cr_api")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MetaDeckAggregate(Base):
    __tablename__ = "meta_deck_aggregates"
    __table_args__ = (
        UniqueConstraint("deck_hash", "mode", name="uq_meta_agg_hash_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deck_hash: Mapped[str] = mapped_column(String(200), index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    cards_csv: Mapped[str] = mapped_column(Text, default="")
    cards_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    total_games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    unique_players: Mapped[int] = mapped_column(Integer, default=0)
    ranking_score: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MetaDeckDailyStat(Base):
    __tablename__ = "meta_deck_daily_stats"
    __table_args__ = (
        UniqueConstraint("deck_hash", "mode", "day", name="uq_meta_daily_hash_mode_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deck_hash: Mapped[str] = mapped_column(String(200), index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD UTC
    games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    unique_players: Mapped[int] = mapped_column(Integer, default=0)


class MetaSnapshot(Base):
    __tablename__ = "meta_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(64), default="cr_api")
    season: Mapped[str] = mapped_column(String(16), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    payload_json: Mapped[str] = mapped_column(Text, default="")


class FsmStorageRecord(Base):
    """Persistent aiogram FSM key-value records."""

    __tablename__ = "fsm_storage"

    record_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


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
            logging.getLogger(__name__).info("Added 'haptic_enabled' column to user_settings table")

        result = await conn.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('user_settings') WHERE name='haptic_intensity'")
        )
        if result.scalar_one_or_none() == 0:
            await conn.execute(
                text(
                    "ALTER TABLE user_settings ADD COLUMN haptic_intensity VARCHAR(10) "
                    "DEFAULT 'standard' NOT NULL"
                )
            )
            logger.info("Added 'haptic_intensity' column to user_settings table")

    await _migrate_battle_cache_opponent()
    await _migrate_battle_cache_trophy()
    # Must run before dedup: ORM select(BattleCache) requires user_deck_json column
    await _migrate_battle_cache_user_deck_json()
    await _migrate_tracked_mine_decks_cards_json()
    await _migrate_battle_cache_dedup()
    await _migrate_users_player_tag_unique()
    await _migrate_ghosteek_pro_columns()


async def _migrate_ghosteek_pro_columns() -> None:
    """Add Pro columns / payment table; revoke legacy free-forever grants."""
    log = logging.getLogger(__name__)
    async with engine.begin() as conn:
        for col, ddl in (
            (
                "started_at",
                "ALTER TABLE subscriptions ADD COLUMN started_at DATETIME",
            ),
            (
                "plan_id",
                "ALTER TABLE subscriptions ADD COLUMN plan_id VARCHAR(32)",
            ),
        ):
            result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM pragma_table_info('subscriptions') "
                    f"WHERE name='{col}'"
                )
            )
            if result.scalar_one_or_none() == 0:
                await conn.execute(text(ddl))
                log.info("Added subscriptions.%s", col)

        # Legacy stub granted is_active=1 AND expires_at IS NULL to everyone.
        # Keep only explicit admin unlimited (plan_id='unlimited').
        await conn.execute(
            text(
                "UPDATE subscriptions SET is_active = 0 "
                "WHERE expires_at IS NULL AND (plan_id IS NULL OR plan_id != 'unlimited') "
                "AND is_active = 1"
            )
        )

    # create_all already creates pro_payments for new DBs; ensure for old DBs too
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def _migrate_battle_cache_user_deck_json() -> None:
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM pragma_table_info('battle_cache') "
                "WHERE name='user_deck_json'"
            )
        )
        if result.scalar_one_or_none() == 0:
            await conn.execute(
                text(
                    "ALTER TABLE battle_cache ADD COLUMN user_deck_json TEXT "
                    "DEFAULT '' NOT NULL"
                )
            )
            logging.getLogger(__name__).info(
                "Added 'user_deck_json' column to battle_cache"
            )


async def _migrate_tracked_mine_decks_cards_json() -> None:
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM pragma_table_info('tracked_mine_decks') "
                "WHERE name='cards_json'"
            )
        )
        if result.scalar_one_or_none() == 0:
            await conn.execute(
                text(
                    "ALTER TABLE tracked_mine_decks ADD COLUMN cards_json TEXT "
                    "DEFAULT '' NOT NULL"
                )
            )
            logging.getLogger(__name__).info(
                "Added 'cards_json' column to tracked_mine_decks"
            )


async def _migrate_battle_cache_trophy() -> None:
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('battle_cache') WHERE name='trophy_change'")
        )
        if result.scalar_one_or_none() == 0:
            await conn.execute(text("ALTER TABLE battle_cache ADD COLUMN trophy_change INTEGER"))
            logging.getLogger(__name__).info("Added 'trophy_change' column to battle_cache")


async def _migrate_battle_cache_opponent() -> None:
    async with engine.begin() as conn:
        for column, ddl in (
            ("opponent_name", "ALTER TABLE battle_cache ADD COLUMN opponent_name VARCHAR(100) DEFAULT ''"),
            ("opponent_tag", "ALTER TABLE battle_cache ADD COLUMN opponent_tag VARCHAR(20) DEFAULT ''"),
        ):
            result = await conn.execute(
                text(f"SELECT COUNT(*) FROM pragma_table_info('battle_cache') WHERE name='{column}'")
            )
            if result.scalar_one_or_none() == 0:
                await conn.execute(text(ddl))
                logging.getLogger(__name__).info("Added '%s' column to battle_cache", column)


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
