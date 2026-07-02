import logging
import re
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.database import User, Subscription

logger = logging.getLogger(__name__)


class ClashRoyaleAPIError(Exception):
    def __init__(self, message: str, status: int = 0, details: str = ""):
        self.status = status
        self.details = details
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


class ClashRoyaleClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.clash_royale_api_key
        if not self.api_key:
            logger.error("Clash Royale API key is not configured")
            raise ClashRoyaleAPIError("API ключ не настроен. Обратитесь к администратору.", 500)
        self._session: aiohttp.ClientSession | None = None
        logger.debug(f"ClashRoyaleClient initialized with API key: {self.api_key[:8]}...")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if settings.clash_royale_proxy_secret:
            headers["X-CR-Proxy-Secret"] = settings.clash_royale_proxy_secret
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self._build_headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            )
            logger.debug("Created new aiohttp session for Clash Royale API")
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("Closed aiohttp session for Clash Royale API")

    async def _request(self, path: str) -> dict | list:
        session = await self._get_session()
        base = settings.clash_royale_api_base.rstrip("/")
        url = f"{base}{path}"
        logger.debug(f"Making API request to: {url}")

        try:
            async with session.get(url) as resp:
                response_text = ""
                try:
                    response_text = await resp.text()
                except Exception as e:
                    logger.warning(f"Failed to read response text: {e}")
                    response_text = ""

                logger.debug(f"API response status: {resp.status} for {url}")

                if resp.status == 404:
                    logger.warning(f"Player not found for path: {path}")
                    raise ClashRoyaleAPIError(
                        "Игрок не найден. Проверьте тег.",
                        404,
                        details=response_text
                    )

                if resp.status == 403:
                    logger.warning(f"API access denied (403) for {url}. Response: {response_text[:200]}")
                    reason = None
                    ip_found = None

                    try:
                        data = json.loads(response_text)
                        if isinstance(data, dict):
                            reason = data.get("reason") or data.get("error")
                            ip_found = data.get("ip")
                    except Exception:
                        pass

                    if not ip_found:
                        m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", response_text)
                        if m:
                            ip_found = m.group(1)

                    ip_error = False
                    if reason and "invalidIp" in reason:
                        ip_error = True
                    elif "invalidIp" in response_text:
                        ip_error = True

                    if ip_error:
                        msg = "API-ключ ограничен по IP."
                        if ip_found:
                            msg += f" Обнаружен IP: {ip_found}"
                        msg += " Добавьте IP сервера в настройки ключа на developer.clashroyale.com или используйте ключ без ограничения."
                        logger.error(f"IP restriction error: {msg}")
                        raise ClashRoyaleAPIError(msg, 403, details=response_text)

                    logger.error(f"API 403 error for {url}: {response_text[:500]}")
                    if reason == "accessDenied" or "Invalid authorization" in response_text:
                        raise ClashRoyaleAPIError(
                            "Неверный CLASH_ROYALE_API_KEY на Railway. "
                            "Скопируйте ключ заново с developer.clashroyale.com.",
                            403,
                            details=response_text,
                        )
                    raise ClashRoyaleAPIError(
                        f"Доступ запрещён (403). Проверьте API ключ.",
                        403,
                        details=response_text
                    )

                if resp.status == 429:
                    logger.warning(f"Rate limit exceeded (429) for {url}")
                    raise ClashRoyaleAPIError(
                        "Слишком много запросов. Подождите немного и попробуйте снова.",
                        429
                    )

                if resp.status != 200:
                    logger.error(f"API error {resp.status} for {url}. Response: {response_text[:500]}")
                    raise ClashRoyaleAPIError(
                        f"Ошибка API ({resp.status}).",
                        resp.status,
                        details=response_text
                    )

                try:
                    data = await resp.json()
                    logger.debug(f"Successfully parsed JSON response for {url}")
                    return data
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response for {url}: {e}. Response: {response_text[:200]}")
                    raise ClashRoyaleAPIError(
                        "Получен некорректный ответ от API.",
                        500,
                        details=response_text
                    )

        except aiohttp.ClientError as e:
            logger.error(f"Network error during API request to {url}: {e}", exc_info=True)
            raise ClashRoyaleAPIError(
                "Ошибка сети. Проверьте подключение к интернету.",
                0,
                details=str(e)
            )
        except Exception as e:
            logger.error(f"Unexpected error during API request to {url}: {e}", exc_info=True)
            raise ClashRoyaleAPIError(
                "Неожиданная ошибка при обращении к API.",
                0,
                details=str(e)
            )

    async def get_player(self, tag: str) -> dict:
        normalized = normalize_tag(tag)
        logger.info(f"Fetching player profile for tag: {normalized}")
        try:
            data = await self._request(f"/players/{encode_tag(tag)}")
            logger.info(f"Successfully fetched player profile: {data.get('name')} ({normalized})")
            return data
        except ClashRoyaleAPIError as e:
            logger.error(f"Failed to fetch player {normalized}: {e}")
            raise

    async def get_battlelog(self, tag: str) -> list:
        normalized = normalize_tag(tag)
        logger.info(f"Fetching battlelog for tag: {normalized}")
        try:
            data = await self._request(f"/players/{encode_tag(tag)}/battlelog")
            battle_count = len(data) if isinstance(data, list) else 0
            logger.info(f"Successfully fetched {battle_count} battles for {normalized}")
            return data
        except ClashRoyaleAPIError as e:
            logger.error(f"Failed to fetch battlelog for {normalized}: {e}")
            raise

    async def get_cards(self) -> dict:
        logger.info("Fetching cards list from API")
        try:
            data = await self._request("/cards")
            card_count = len(data.get("items", [])) if isinstance(data, dict) else 0
            logger.info(f"Successfully fetched {card_count} cards")
            return data
        except ClashRoyaleAPIError as e:
            logger.error(f"Failed to fetch cards: {e}")
            raise


def validate_tag(tag: str) -> bool:
    normalized = normalize_tag(tag)
    return bool(re.match(r"^#[0289PYLQGRJCUV]{3,15}$", normalized))


class SubscriptionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_user(self, telegram_id: int) -> User:
        logger.debug(f"Getting or creating user for telegram_id: {telegram_id}")
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            logger.info(f"Creating new user for telegram_id: {telegram_id}")
            user = User(telegram_id=telegram_id)
            self.session.add(user)
            await self.session.flush()
            sub = Subscription(user_id=user.id, is_active=False)
            self.session.add(sub)
            await self.session.commit()
            await self.session.refresh(user)
            logger.debug(f"Created new user with id: {user.id}")
        return user

    async def link_player(self, user: User, tag: str, player_data: dict) -> User:
        normalized = normalize_tag(tag)
        logger.info(f"Linking player {normalized} to user {user.telegram_id}")
        user.player_tag = normalized
        user.player_name = player_data.get("name")
        arena = player_data.get("arena", {})
        user.arena_id = arena.get("id")
        user.trophies = player_data.get("trophies")
        await self.session.commit()
        await self.session.refresh(user)
        logger.info(
            f"Successfully linked player: {user.player_name} ({user.player_tag}), "
            f"arena: {user.arena_id}, trophies: {user.trophies}"
        )
        return user

    async def link_player(self, user: User, tag: str, player_data: dict) -> User:
        user.player_tag = normalize_tag(tag)
        user.player_name = player_data.get("name")
        arena = player_data.get("arena", {})
        user.arena_id = arena.get("id")
        user.trophies = player_data.get("trophies")
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def has_active_subscription(self, user: User) -> bool:
        result = await self.session.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            return False
        if not sub.is_active:
            return False
        if sub.expires_at and _utc_aware(sub.expires_at) < datetime.now(timezone.utc):
            sub.is_active = False
            await self.session.commit()
            return False
        return True

    async def activate_trial(self, user: User) -> tuple[bool, str]:
        result = await self.session.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
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
        result = await self.session.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
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
        result = await self.session.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            sub = Subscription(user_id=user.id)
            self.session.add(sub)

        sub.is_active = True
        sub.expires_at = None
        await self.session.commit()

    async def get_subscription_info(self, user: User) -> dict:
        result = await self.session.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        sub = result.scalar_one_or_none()
        if sub is None or not sub.is_active:
            return {"active": False, "expires_at": None, "trial_used": False}

        expires = _utc_aware(sub.expires_at)
        active = expires is None or expires > datetime.now(timezone.utc)
        return {
            "active": active,
            "expires_at": expires,
            "trial_used": sub.trial_used,
        }
