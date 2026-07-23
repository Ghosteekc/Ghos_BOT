"""Audit duplicate battles in battle_cache (read-only)."""

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
                "SELECT player_tag, battle_time, COUNT(*) AS cnt "
                "FROM battle_cache "
                "GROUP BY player_tag, battle_time "
                "HAVING cnt > 1 "
                "ORDER BY cnt DESC, player_tag, battle_time"
            )
        )
        rows = result.fetchall()

    if not rows:
        print("No duplicate (player_tag, battle_time) groups found.")
        return 0

    total_extra = sum(int(cnt) - 1 for _, _, cnt in rows)
    print(f"Found {len(rows)} duplicate groups ({total_extra} extra rows):")
    for player_tag, battle_time, cnt in rows:
        print(f"  {player_tag}  {battle_time}  x{cnt}")
    print("\nNo rows were deleted. Resolve manually if needed, then restart bot to create unique index.")
    return len(rows)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(audit_duplicates()))
