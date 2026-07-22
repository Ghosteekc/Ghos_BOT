"""Единственный backend-клиент Clash Royale API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.database import Subscription, User

logger = logging.getLogger(__name__)

_CONFIG_ERROR_STATUSES = frozenset({401, 403})


class ClashRoyaleAPIError(Exception):
    def __init__(
        self,
        message: str,
        status: int = 0,
        details: str = "",
        *,
        retryable: bool = False,
        config_error: bool = False,
        retry_after: float | None = None,
    ):
        self.status = status
        self.details = details
        self.retryable = retryable
        self.config_error = config_error or status in _CONFIG_ERROR_STATUSES
        self.retry_after = retry_after
        super().__init__(message)


def normalize_tag(tag: str) -> str:
    tag = tag.strip().upper().replace(" ", "")
    if not tag.startswith("#"):
        tag = f"#{tag}"
    return tag


def encode_tag(tag: str) -> str:
    return quote(normalize_tag(tag), safe="")


def _utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _retry_delay_seconds(response: aiohttp.ClientResponse | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.5, float(retry_after))
            except ValueError:
                pass
    base = max(0.5, settings.cr_api_retry_base_delay_sec)
    return min(base * (2 ** (attempt - 1)), 30.0)


def _parse_error_body(response_text: str) -> tuple[str | None, str | None]:
    reason: str | None = None
    ip_found: str | None = None
    try:
        data = json.loads(response_text)
        if isinstance(data, dict):
            reason = data.get("reason") or data.get("error")
            ip_found = data.get("ip")
    except json.JSONDecodeError:
        pass
    if not ip_found:
        match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", response_text)
        if match:
            ip_found = match.group(1)
    return reason, ip_found


def _config_error_message(status: int, response_text: str) -> ClashRoyaleAPIError:
    reason, ip_found = _parse_error_body(response_text)

    if status == 401 or reason == "accessDenied" or "Invalid authorization" in response_text:
        return ClashRoyaleAPIError(
            "Сервис данных игры настроен неверно. Обратитесь к администратору.",
            status,
            details=response_text,
            config_error=True,
        )

    if (reason and "invalidIp" in reason) or "invalidIp" in response_text:
        msg = "Доступ к данным игры ограничен по IP."
        if ip_found:
            msg += f" Обнаружен IP: {ip_found}"
        msg += " Обратитесь к администратору приложения."
        return ClashRoyaleAPIError(msg, status, details=response_text, config_error=True)

    if status == 403:
        return ClashRoyaleAPIError(
            "Сервис данных игры настроен неверно. Обратитесь к администратору.",
            status,
            details=response_text,
            config_error=True,
        )

    return ClashRoyaleAPIError(
        "Сервис данных игры настроен неверно. Обратитесь к администратору.",
        status,
        details=response_text,
        config_error=True,
    )


class ClashRoyaleClient:
    """HTTP-клиент CR API. Токен только из settings (env)."""

    def __init__(self, api_key: str | None = None):
        key = api_key or settings.clash_royale_api_key
        if not key or key == "your_clash_royale_api_key":
            logger.error("Clash Royale API key is not configured")
            raise ClashRoyaleAPIError(
                "Сервис данных игры не настроен. Обратитесь к администратору.",
                500,
                config_error=True,
            )
        self._api_key = key
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> ClashRoyaleClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        await self.close()
        return False

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        if settings.clash_royale_proxy_secret:
            headers["X-CR-Proxy-Secret"] = settings.clash_royale_proxy_secret
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=settings.cr_api_timeout_sec)
            self._session = aiohttp.ClientSession(headers=self._build_headers(), timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(self, path: str) -> dict | list:
        max_attempts = max(1, settings.cr_api_retry_max)
        last_error: ClashRoyaleAPIError | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                return await self._request_once(path, attempt=attempt, max_attempts=max_attempts)
            except ClashRoyaleAPIError as exc:
                last_error = exc
                if exc.config_error or not exc.retryable or attempt >= max_attempts:
                    raise
                delay = exc.retry_after if exc.retry_after is not None else _retry_delay_seconds(None, attempt)
                logger.warning(
                    "CR API retry %s/%s for %s in %.1fs (status=%s)",
                    attempt,
                    max_attempts,
                    path,
                    delay,
                    exc.status,
                )
                await asyncio.sleep(delay)

        if last_error:
            raise last_error
        raise ClashRoyaleAPIError("Не удалось выполнить запрос к API игры.", 0, retryable=False)

    async def _request_once(self, path: str, *, attempt: int, max_attempts: int) -> dict | list:
        session = await self._get_session()
        base = settings.clash_royale_api_base.rstrip("/")
        url = f"{base}{path}"
        started = time.monotonic()

        try:
            async with session.get(url) as resp:
                response_text = await resp.text()
                duration_ms = int((time.monotonic() - started) * 1000)
                logger.info(
                    "CR API GET %s status=%s duration_ms=%s attempt=%s/%s",
                    path,
                    resp.status,
                    duration_ms,
                    attempt,
                    max_attempts,
                )

                if resp.status == 404:
                    raise ClashRoyaleAPIError(
                        "Игрок не найден. Проверьте тег.",
                        404,
                        details=response_text,
                    )

                if resp.status in _CONFIG_ERROR_STATUSES:
                    logger.error(
                        "CR API configuration error status=%s path=%s reason=%s",
                        resp.status,
                        path,
                        _parse_error_body(response_text)[0],
                    )
                    raise _config_error_message(resp.status, response_text)

                if resp.status == 429:
                    raise ClashRoyaleAPIError(
                        "Слишком много запросов. Подождите немного и попробуйте снова.",
                        429,
                        details=response_text,
                        retryable=True,
                        retry_after=_retry_delay_seconds(resp, attempt),
                    )

                if resp.status != 200:
                    logger.error("CR API unexpected status=%s path=%s", resp.status, path)
                    raise ClashRoyaleAPIError(
                        f"Ошибка загрузки данных игры ({resp.status}).",
                        resp.status,
                        details=response_text,
                    )

                if not response_text:
                    raise ClashRoyaleAPIError(
                        "Получен пустой ответ от сервера игры.",
                        500,
                    )
                try:
                    return json.loads(response_text)
                except json.JSONDecodeError as exc:
                    logger.error("CR API invalid JSON path=%s", path)
                    raise ClashRoyaleAPIError(
                        "Получен некорректный ответ от сервера игры.",
                        500,
                        details=response_text[:200],
                    ) from exc

        except asyncio.TimeoutError as exc:
            logger.warning("CR API timeout path=%s attempt=%s/%s", path, attempt, max_attempts)
            err = ClashRoyaleAPIError(
                "Сервис данных игры не ответил вовремя. Попробуйте позже.",
                0,
                retryable=True,
            )
            raise err from exc
        except aiohttp.ClientError as exc:
            logger.warning("CR API network error path=%s attempt=%s/%s: %s", path, attempt, max_attempts, exc)
            raise ClashRoyaleAPIError(
                "Ошибка сети. Проверьте подключение к интернету.",
                0,
                details=str(exc),
                retryable=True,
            ) from exc

    async def get_player(self, tag: str) -> dict:
        normalized = normalize_tag(tag)
        data = await self._request(f"/players/{encode_tag(tag)}")
        if not isinstance(data, dict):
            raise ClashRoyaleAPIError("Некорректный ответ профиля игрока.", 500)
        logger.info("CR API player fetched tag=%s name=%s", normalized, data.get("name", "?"))
        return data

    async def get_battlelog(self, tag: str) -> list:
        normalized = normalize_tag(tag)
        data = await self._request(f"/players/{encode_tag(tag)}/battlelog")
        if not isinstance(data, list):
            raise ClashRoyaleAPIError("Некорректный ответ журнала боёв.", 500)
        logger.info("CR API battlelog fetched tag=%s battles=%s", normalized, len(data))
        return data

    async def get_cards(self) -> dict:
        data = await self._request("/cards")
        if not isinstance(data, dict):
            raise ClashRoyaleAPIError("Некорректный ответ списка карт.", 500)
        card_count = len(data.get("items", []))
        logger.info("CR API cards fetched count=%s", card_count)
        return data


def validate_tag(tag: str) -> bool:
    normalized = normalize_tag(tag)
    return bool(re.match(r"^#[0289PYLQGRJCUV]{3,15}$", normalized))


class SubscriptionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_user(self, telegram_id: int) -> User:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(telegram_id=telegram_id)
            self.session.add(user)
            await self.session.flush()
            sub = Subscription(user_id=user.id, is_active=True, expires_at=None)
            self.session.add(sub)
            await self.session.commit()
            await self.session.refresh(user)
        else:
            await self._ensure_free_access(user)
        return user

    async def _ensure_free_access(self, user: User) -> None:
        result = await self.session.execute(select(Subscription).where(Subscription.user_id == user.id))
        sub = result.scalar_one_or_none()
        if sub is None:
            sub = Subscription(user_id=user.id, is_active=True, expires_at=None)
            self.session.add(sub)
            await self.session.commit()
            return
        if not sub.is_active or sub.expires_at is not None:
            sub.is_active = True
            sub.expires_at = None
            await self.session.commit()

    async def link_player(self, user: User, tag: str, player_data: dict) -> User:
        normalized = normalize_tag(tag)
        user.player_tag = normalized
        user.player_name = player_data.get("name")
        arena = player_data.get("arena", {})
        user.arena_id = arena.get("id")
        user.trophies = player_data.get("trophies")
        await self.session.commit()
        await self.session.refresh(user)
        logger.info("Linked player %s to telegram_id=%s", normalized, user.telegram_id)
        return user

    async def has_active_subscription(self, user: User) -> bool:
        return True

    async def activate_trial(self, user: User) -> tuple[bool, str]:
        result = await self.session.execute(select(Subscription).where(Subscription.user_id == user.id))
        sub = result.scalar_one_or_none()
        if sub is None:
            sub = Subscription(user_id=user.id)
            self.session.add(sub)

        if sub.trial_used:
            return False, "Пробный период уже использован."

        sub.is_active = True
        sub.trial_used = True
        sub.expires_at = datetime.now(timezone.utc) + timedelta(days=settings.trial_days)
        await self.session.commit()
        return True, f"Пробный период активирован на {settings.trial_days} дней!"

    async def activate_subscription(self, user: User, days: int = 30) -> None:
        result = await self.session.execute(select(Subscription).where(Subscription.user_id == user.id))
        sub = result.scalar_one_or_none()
        if sub is None:
            sub = Subscription(user_id=user.id)
            self.session.add(sub)

        now = datetime.now(timezone.utc)
        expires_at = _utc_aware(sub.expires_at)
        if expires_at and expires_at > now:
            sub.expires_at = expires_at + timedelta(days=days)
        else:
            sub.expires_at = now + timedelta(days=days)
        sub.is_active = True
        await self.session.commit()

    async def activate_unlimited_subscription(self, user: User) -> None:
        result = await self.session.execute(select(Subscription).where(Subscription.user_id == user.id))
        sub = result.scalar_one_or_none()
        if sub is None:
            sub = Subscription(user_id=user.id)
            self.session.add(sub)

        sub.is_active = True
        sub.expires_at = None
        await self.session.commit()

    async def get_subscription_info(self, user: User) -> dict:
        await self._ensure_free_access(user)
        return {"active": True, "expires_at": None, "trial_used": True}
