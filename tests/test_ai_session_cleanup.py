"""Focused regression tests for idle Ghosteek AI session cleanup."""

from __future__ import annotations

import asyncio
import time
import unittest

from bot.services.ghosteek_ai.conversation.state import SESSION_TTL_SECONDS
from bot.services.ghosteek_ai.memory.in_memory import (
    InMemoryMemoryProvider,
    run_periodic_cleanup,
)


class SessionCleanupTests(unittest.IsolatedAsyncioTestCase):
    def test_sweep_removes_only_expired_sessions(self) -> None:
        provider = InMemoryMemoryProvider()
        expired = provider.get_or_create(1)
        active = provider.get_or_create(2)
        now = time.time()
        expired.updated_at = now - SESSION_TTL_SECONDS - 1
        active.updated_at = now - SESSION_TTL_SECONDS

        self.assertEqual(SESSION_TTL_SECONDS, 45 * 60)
        self.assertEqual(provider.prune_expired(now=now), 1)
        self.assertNotIn(1, provider._sessions)
        self.assertIs(provider._sessions[2], active)

    async def test_periodic_cleanup_and_shutdown(self) -> None:
        provider = InMemoryMemoryProvider()
        stale = provider.get_or_create(1)
        active = provider.get_or_create(2)
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            run_periodic_cleanup(provider, stop_event, interval_seconds=0.01)
        )
        try:
            await asyncio.sleep(0)
            self.assertIn(1, provider._sessions)
            stale.updated_at = time.time() - SESSION_TTL_SECONDS - 1

            async def wait_until_pruned() -> None:
                while 1 in provider._sessions:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_until_pruned(), timeout=1)
            self.assertNotIn(1, provider._sessions)
            self.assertIs(provider._sessions[2], active)
        finally:
            stop_event.set()
            await asyncio.wait_for(task, timeout=1)

        self.assertTrue(task.done())
        self.assertFalse(task.cancelled())
        provider.get_or_create(3).updated_at = time.time() - SESSION_TTL_SECONDS - 1
        await asyncio.sleep(0.02)
        self.assertIn(3, provider._sessions)


if __name__ == "__main__":
    unittest.main()
