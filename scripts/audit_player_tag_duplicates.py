"""Audit duplicate player_tag values in users (read-only)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from bot.models.database import async_session, init_db


async def audit_duplicates() -> int:
    await init_db()
    async with async_session() as session:
        result = await session.execute(
            text(
                "SELECT player_tag, COUNT(*) AS cnt "
                "FROM users "
                "WHERE player_tag IS NOT NULL "
                "GROUP BY player_tag "
                "HAVING cnt > 1 "
                "ORDER BY cnt DESC, player_tag"
            )
        )
        rows = result.fetchall()

    if not rows:
        print("No duplicate player_tag values found.")
        return 0

    print(f"Found {len(rows)} duplicate player_tag groups:")
    async with async_session() as session:
        for player_tag, cnt in rows:
            users = await session.execute(
                text(
                    "SELECT id, telegram_id, player_name, created_at "
                    "FROM users WHERE player_tag = :tag ORDER BY id"
                ),
                {"tag": player_tag},
            )
            print(f"\n  {player_tag}  x{cnt}")
            for user_id, telegram_id, name, created_at in users.fetchall():
                print(f"    user_id={user_id} telegram_id={telegram_id} name={name!r} created={created_at}")

    print("\nNo users were modified. Resolve conflicts manually, then restart bot to create unique index.")
    return len(rows)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(audit_duplicates()))
