"""SQLite-backed aiogram FSM storage (survives bot restarts)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from aiogram.exceptions import DataNotDictLikeError
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, StateType, StorageKey

from bot.models import database
from bot.models.database import FsmStorageRecord

logger = logging.getLogger(__name__)


class SqliteStorage(BaseStorage):
    def __init__(self) -> None:
        self._key_builder = DefaultKeyBuilder()

    def _record_key(self, key: StorageKey, part: str) -> str:
        return self._key_builder.build(key, part)  # type: ignore[arg-type]

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        record_key = self._record_key(key, "state")
        state_str = state.state if isinstance(state, State) else state
        async with database.async_session() as session:
            row = await session.get(FsmStorageRecord, record_key)
            if state_str is None:
                if row is not None:
                    await session.delete(row)
            elif row is None:
                session.add(FsmStorageRecord(record_key=record_key, value=state_str))
            else:
                row.value = state_str
            await session.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        record_key = self._record_key(key, "state")
        async with database.async_session() as session:
            row = await session.get(FsmStorageRecord, record_key)
            return row.value if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        if not isinstance(data, dict):
            msg = f"Data must be a dict or dict-like object, got {type(data).__name__}"
            raise DataNotDictLikeError(msg)

        record_key = self._record_key(key, "data")
        payload = json.dumps(data, ensure_ascii=False)
        async with database.async_session() as session:
            row = await session.get(FsmStorageRecord, record_key)
            if row is None:
                session.add(FsmStorageRecord(record_key=record_key, value=payload))
            else:
                row.value = payload
            await session.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        record_key = self._record_key(key, "data")
        async with database.async_session() as session:
            row = await session.get(FsmStorageRecord, record_key)
            if not row or not row.value:
                return {}
            try:
                parsed = json.loads(row.value)
            except json.JSONDecodeError:
                logger.warning("Invalid FSM JSON for key %s", record_key)
                return {}
            return parsed if isinstance(parsed, dict) else {}

    async def close(self) -> None:
        return None
