# BOT_AUDIT — Ghosteek CR Assistant (Clash Royale Coach)

**Дата аудита:** 2026-07-23  
**Объект:** репозиторий backend + бот (`G:/проги/ss`, GitHub: `Ghosteekc/Ghos_BOT`)  
**Связанный frontend:** Mini App в отдельном репозитории `Ghosteekc/Ghos_web` (`G:/проги/webapp`)  
**Метод:** статический анализ исходного кода. Runtime-тесты, production-логи и содержимое `.env` **не проверялись**.

> **Важно:** в отчёте **нет** реальных значений секретов, токенов, паролей и персональных данных пользователей.

---

## Содержание

1. [Структура проекта](#1-структура-проекта)
2. [Telegram-бот](#2-telegram-бот)
3. [Clash Royale API](#3-clash-royale-api)
4. [База данных](#4-база-данных)
5. [Фоновая синхронизация](#5-фоновая-синхронизация)
6. [FastAPI / backend](#6-fastapi--backend)
7. [WebApp / Mini App](#7-webapp--mini-app)
8. [Конфигурация и секреты](#8-конфигурация-и-секреты)
9. [Деплой](#9-деплой)
10. [Таблица проблем](#10-таблица-проблем)
11. [Итоговая классификация](#11-итоговая-классификация)
12. [Рекомендуемый порядок исправлений](#12-рекомендуемый-порядок-исправлений)

---

## 1. Структура проекта

### 1.1. Общая архитектура

Проект — **монолитный Python-процесс**, в котором одновременно работают:

| Компонент | Точка входа | Порт / канал |
|-----------|-------------|--------------|
| Telegram-бот (long polling) | `bot/main.py` → `dp.start_polling()` | Telegram API |
| FastAPI (REST API для Mini App) | `bot/main.py` → `run_api()` / uvicorn | `API_HOST:API_PORT` (по умолчанию `0.0.0.0:8080`) |
| Фоновая синхронизация боёв | `bot/main.py` → `sync_service.run_periodic()` | внутренний asyncio task |
| Localtunnel (опционально, Windows) | `bot/services/tunnel_manager.py` → `start-tunnel.ps1` | HTTPS `https://{subdomain}.loca.lt` |

Mini App (React) деплоится **отдельно** на Vercel и проксирует `/api/*` на backend через `vercel.json`.

### 1.2. Основные папки и назначение

| Путь | Назначение |
|------|------------|
| `bot/main.py` | Единая точка запуска: БД, CR API smoke-test, polling, API, sync, tunnel |
| `bot/config.py` | Pydantic Settings, загрузка `.env` |
| `bot/handlers/` | Aiogram-роутеры (команды, кнопки) |
| `bot/keyboards/` | Reply-клавиатуры |
| `bot/middleware/` | Middleware (инъекция `user` для callback) |
| `bot/api/` | FastAPI: `app.py`, `auth.py`, `deps.py`, `errors.py`, `schemas.py`, `routes/` |
| `bot/models/database.py` | SQLAlchemy модели, engine, `init_db()` |
| `bot/services/` | Бизнес-логика: CR API, бои, колоды, sync, meta, deckshop и др. |
| `bot/data/` | Статические JSON/Python данные (карты, колоды, DeckShop counters) |
| `bot/user_errors.py` | Коды пользовательских ошибок (бот + API) |
| `bot/static/cards/` | Статика иконок карт для API |
| `scripts/localtunnel/` | Localtunnel supervisor (`start-tunnel.ps1`, npm deps) |
| `scripts/cr-proxy/` | Конфиг nginx для VPS-прокси к CR API |
| `scripts/` | Утилиты генерации данных, проверки DeckShop |
| `tests/` | Unit-тесты (`test_auth.py`, `test_clash_api.py`, `test_user_errors.py`) |
| `.env.example` | Шаблон переменных окружения |
| `HOW_TO_RUN.md`, `PROJECT_CONTEXT.md`, `README.md` | Документация |

**Не в git / игнорируется:** `.env`, `*.db`, `webapp/` (в `.gitignore` backend-репо), логи туннеля.

### 1.3. Точки запуска

**Telegram-бот + backend:**
```bash
python -m bot.main
```
Файл: `bot/main.py`, блок `if __name__ == "__main__"`.

**Localtunnel вручную (Windows):**
```powershell
cd scripts/localtunnel
.\start-tunnel.ps1 -Subdomain ghosteekcr
```

**Mini App (отдельный репозиторий):**
```bash
cd webapp && npm run dev    # dev
cd webapp && npm run build  # prod → Vercel
```

### 1.4. Фоновые задачи и сервисы

| Задача | Файл | Триггер |
|--------|------|---------|
| Периодическая sync боёв всех пользователей | `bot/services/sync_service.py` → `run_periodic()` | `asyncio.create_task` в `main.py` |
| Meta refresh (топ-колоды) | `bot/services/meta_analyzer.py` → `refresh_meta_background()` | Вызывается в конце каждого sync-цикла |
| Auto-tunnel | `bot/services/tunnel_manager.py` | При `TUNNEL_AUTO_START=true` (Windows) |

In-memory кэши (не переживают рестарт процесса):

- `bot/services/battle_session_cache.py` — список боёv per `telegram_id` (TTL 5 мин)
- `bot/services/meta_analyzer.py` — `_cache` meta decks
- `bot/handlers/analysis.py`, `customization.py` — `_battle_cache`, `_opponents_cache` (**роутеры не подключены к Dispatcher**, см. §2)

### 1.5. База данных

SQLite через `aiosqlite` (по умолчанию `./cr_bot.db`). Схема создаётся через `Base.metadata.create_all()` без Alembic. Подробнее — §4.

### 1.6. Clash Royale API

Единственный HTTP-клиент: `bot/services/clash_api.py` → `ClashRoyaleClient`. Подробнее — §3.

### 1.7. WebApp / Mini App

Frontend: React + Vite + TypeScript (`G:/прогi/webapp`). Backend авторизует запросы через заголовок `X-Telegram-Init-Data`. Подробнее — §7.

### 1.8. Взаимодействие компонентов

```
Telegram User
    ├─► aiogram polling (handlers: start, player, support, admin)
    └─► Mini App (Vercel) ──► /api/* ──► vercel.json rewrite ──► localtunnel/VPS ──► FastAPI :8080
                                        X-Telegram-Init-Data
FastAPI ──► SQLite + bot/services/* ──► ClashRoyaleClient ──► api.clashroyale.com (или VPS proxy)
```

---

## 2. Telegram-бот

### 2.1. Запуск

- **Файл:** `bot/main.py`, функция `main()`.
- Создаётся `Bot(token=settings.bot_token)`, `Dispatcher()`.
- Перед polling: `await bot.delete_webhook(drop_pending_updates=True)` — снижает риск `TelegramConflictError` при двойном webhook/polling.
- Polling: `await dp.start_polling(bot)`.

### 2.2. Подключённые роутеры

В `main.py` регистрируются **только**:

| Роутер | Файл | Назначение |
|--------|------|------------|
| `start.router` | `bot/handlers/start.py` | `/start`, `/help` |
| `player.router` | `bot/handlers/player.py` | `/link`, `/profile`, регистрация по тегу |
| `support.router` | `bot/handlers/support.py` | Кнопка «Поддержка» |
| `admin.router` | `bot/handlers/admin.py` | `/admin_sub`, `/deckshop_check`, `/sync_now` |

### 2.3. Неподключённые роутеры (подтверждено по коду)

Следующие файлы **существуют**, но **не включены** в `dp.include_router()`:

| Файл | Содержимое |
|------|------------|
| `bot/handlers/analysis.py` | Анализ боёv, винрейт, `/stats` |
| `bot/handlers/customization.py` | Колоды соперников, контр-колоды, синергии |
| `bot/handlers/subscription.py` | Trial, Telegram Stars, оплата |

**Вывод:** функционал анализа/подписки в **чате бота** фактически недоступен; основной UX перенесён в Mini App.

### 2.4. Команды и обработчики

| Команда / кнопка | Handler | Файл |
|------------------|---------|------|
| `/start` | `cmd_start` | `start.py` |
| `/help` | `cmd_help` | `start.py` |
| `/link`, «📝 Регистрация» | `cmd_link`, `btn_registration`, `handle_pending_tag` | `player.py` |
| `/profile`, «👤 Профиль» | `cmd_profile` | `player.py` |
| «💬 Поддержка» | `cmd_support` | `support.py` |
| `/admin_sub` | `cmd_admin_sub` | `admin.py` |
| `/deckshop_check` | `cmd_deckshop_check` | `admin.py` |
| `/sync_now` | `cmd_sync_now` | `admin.py` |

### 2.5. Callback-кнопки

Активные callback-обработчики — только в **неподключённых** `analysis.py`, `customization.py`, `subscription.py`. В подключённых роутерах callback **не используются**.

### 2.6. FSM / состояния

**FSM не используется** (поиск по `bot/` — совпадений нет).

Вместо FSM для привязки тега — **in-memory set** `_pending_link: set[int]` в `bot/handlers/player.py`.  
**Последствие:** состояние «ожидаю тег» **теряется при перезапуске процесса** и **не разделяется** между несколькими инстансами.

### 2.7. Регистрация пользователей

- При `/start` и при API-запросах: `SubscriptionService.get_or_create_user(telegram_id)` (`clash_api.py`).
- Создаётся запись `User` + `Subscription` (бесплатный доступ по умолчанию).
- Привязка CR-тега: `SubscriptionService.link_player()` после успешного `ClashRoyaleClient.get_player()`.

### 2.8. Авторизация в боте

- Авторизация Telegram — через `message.from_user.id` (доверие платформе Telegram).
- Admin-команды: проверка `message.from_user.id in get_admin_telegram_ids()` (`admin.py`).

### 2.9. Подписка

- `SubscriptionService.has_active_subscription()` **всегда возвращает `True`** (`clash_api.py:352-353`).
- `_ensure_free_access()` принудительно активирует подписку без срока.
- Логика trial/Stars есть в `subscription.py`, но роутер **не подключён**; оплата через Stars **не доступна из чата**.

### 2.10. Поддержка

`support.py`: если задан `SUPPORT_USERNAME` — ссылка на аккаунт; иначе fallback на admin или код ошибки `E900`.

### 2.11. Обработка ошибок

- Централизованные коды: `bot/user_errors.py` (`user_message()`, `log_error()`).
- Handlers `player.py`, `analysis.py`, `customization.py`, `admin.py` используют коды `E001`–`E080`.
- Технические детали CR API **не показываются** пользователю; логируются на сервере.

### 2.12. Повторный запуск / завершение

**При старте:**
- `init_db()`, smoke-test CR API (ошибка не блокирует старт).
- Запуск sync task, API task, optional tunnel.
- `delete_webhook` перед polling.

**При shutdown (`finally` в `main.py`):**
- `stop_event.set()` для sync.
- Остановка tunnel process.
- `api_task.cancel()`, `sync_task.cancel()` с `wait_for` timeout `sync_shutdown_timeout_sec`.

**Риски повторного запуска (подтверждено / предположения):**

| Сценарий | Статус |
|----------|--------|
| Два процесса `python -m bot.main` на одном токене | **CRITICAL риск** — TelegramConflictError (частично mitigated webhook delete) |
| Два tunnel supervisor | Mitigated: `Stop-ExistingTunnels` в PS1 и `tunnel_manager` |
| In-memory `_pending_link` после рестарта | **Подтверждено** — состояние сбрасывается |

---

## 3. Clash Royale API

### 3.1. Хранение токена

| Аспект | Реализация |
|--------|------------|
| Источник | `settings.clash_royale_api_key` ← env `CLASH_ROYALE_API_KEY` (`config.py`) |
| Placeholder | `"your_clash_royale_api_key"` блокирует клиент (`clash_api.py:131-137`) |
| Логирование | Токен **не логируется**; логируются path, status, duration |
| API response | Токен **не возвращается** |
| Frontend | **Нет доступа** к CR API (grep webapp — совпадений нет) |
| Optional proxy secret | `CLASH_ROYALE_PROXY_SECRET` → заголовок `X-CR-Proxy-Secret` |

**Примечание:** `ClashRoyaleClient.__init__(api_key: str | None = None)` допускает передачу ключа из кода; в production-вызовах параметр **не передаётся** (grep `ClashRoyaleClient(` без аргументов).

### 3.2. Выполнение запросов

- **Единственный клиент:** `bot/services/clash_api.py` → `ClashRoyaleClient`.
- HTTP: `aiohttp.ClientSession`, base URL `CLASH_ROYALE_API_BASE`.
- Методы: `get_player()`, `get_battlelog()`, `get_cards()`.
- Прямых `aiohttp`/`requests` вызовов к CR API вне клиента **не обнаружено**.

**Потребители клиента (неполный список):** `main.py`, `sync_service.py`, `battle_service.py`, `meta_analyzer.py`, `arena_decks.py`, `top_players.py`, `card_registry.py`, API routes (`profile`, `misc`, `decks`), handlers.

### 3.3. IP / proxy

- При прямом доступе IP = IP машины, где работает бот.
- При VPS proxy: `CLASH_ROYALE_API_BASE=http://VPS/v1` + whitelist IP на developer.clashroyale.com (`scripts/cr-proxy/`).
- Ошибка `invalidIp` обрабатывается в `_config_error_message()` с user-friendly текстом (может включить **обнаруженный IP из ответа CR**, не секрет).

### 3.4. HTTP-коды

| Код | Обработка (`_request_once`) | Retry |
|-----|----------------------------|-------|
| 200 | JSON parse | — |
| 401, 403 | `_config_error_message()`, `config_error=True` | **Нет** |
| 404 | «Игрок не найден» | **Нет** |
| 429 | `retryable=True`, `Retry-After` / backoff | **Да** (до `CR_API_RETRY_MAX`) |
| 5xx / прочие ≠200 | `ClashRoyaleAPIError` | **Нет** (если не retryable) |
| Timeout | `retryable=True` | **Да** |
| Network (`aiohttp.ClientError`) | `retryable=True` | **Да** |

Настройки: `CR_API_TIMEOUT_SEC`, `CR_API_RETRY_MAX`, `CR_API_RETRY_BASE_DELAY_SEC`.

### 3.5. Падение бота при ошибках API

| Место | Поведение |
|-------|-----------|
| `main.py` startup smoke-test | Exception ловится, бот **продолжает** старт |
| Handlers | `ClashRoyaleAPIError` → user error code, бот **не падает** |
| `sync_service.sync_user_battles` | CR error → log + return 0, цикл **продолжается** |
| `run_periodic` | Exception в цикле → log, loop **продолжается** |
| Необработанный exception в handler | **Может** прервать обработку одного update (aiogram default) |

**Вывод:** CR API ошибки **не ронят** процесс целиком; подтверждено по `sync_service.py` и `main.py`.

### 3.6. Места, где sync может пострадать от API

- `sync_user_battles`: при CR error возвращает 0 (данные не обновляются, задача жива).
- `meta_analyzer.refresh_meta_background`: ошибки CR API логируются; static fallback meta decks (`meta_decks.py`).
- `_fetch_battlelog` дополнительный `asyncio.wait_for` (`sync_cr_api_timeout_sec`) поверх client timeout — двойной timeout.

---

## 4. База данных

### 4.1. СУБД

- **По умолчанию:** SQLite (`DATABASE_URL=sqlite+aiosqlite:///./cr_bot.db`).
- **Production-ready альтернатива:** PostgreSQL через изменение `DATABASE_URL` (в коде нет специфики PG, но SQLAlchemy async поддерживает).

### 4.2. Таблицы / модели (`bot/models/database.py`)

| Таблица | Модель | Ключевые поля |
|---------|--------|---------------|
| `users` | `User` | `telegram_id` **UNIQUE**, `player_tag`, `player_name`, `arena_id`, `trophies` |
| `subscriptions` | `Subscription` | `user_id` **UNIQUE**, `is_active`, `expires_at`, `trial_used` |
| `card_preferences` | `CardPreference` | `user_id`, `card_name`, `play_count` |
| `battle_cache` | `BattleCache` | `player_tag`, `battle_time`, decks, `result`, `analysis` |
| `favorite_decks` | `FavoriteDeck` | `user_id`, `deck_key` |

### 4.3. Миграции

- **Alembic / миграций нет.**
- `init_db()` → `create_all()`.
- Единственная ad-hoc миграция: добавление колонки `trophies` через raw SQL + `pragma_table_info` (`database.py:93-101`).

### 4.4. Race conditions и дубликаты

| Риск | Статус | Детали |
|------|--------|--------|
| Дубликат `User` по `telegram_id` | **Mitigated** | UNIQUE на `telegram_id`; при race — IntegrityError (**обработка в коде не найдена**) |
| Дубликат `BattleCache` | **Подтверждено — риск** | Нет UNIQUE(`player_tag`, `battle_time`); check-then-insert в `sync_service.py`, `battle_service.py`, `analysis.py` |
| Один CR-тег у нескольких Telegram users | **Подтверждено — возможно** | Нет UNIQUE на `player_tag` |
| Параллельный sync одного user | **Mitigated частично** | `_sync_lock` сериализует `sync_all_once`; per-user параллелизм внутри цикла **нет** |

### 4.5. Транзакции и ошибки подключения

- Сессии через `async_session()` context manager.
- Commit точечный (после batch insert battles, link player и т.д.).
- **Нет** явной обработки ошибок подключения к SQLite/PostgreSQL на уровне engine.
- **Невозможно подтвердить по текущему коду** поведение при disk full / locked database без runtime-теста.

---

## 5. Фоновая синхронизация

### 5.1. Задачи

| Задача | Функция | Интервал |
|--------|---------|----------|
| Sync боёv всех пользователей | `run_periodic()` → `_run_sync_cycle()` → `sync_all_once()` | `SYNC_INTERVAL_MINUTES` (default 60 мин) |
| Meta refresh | `_refresh_meta_safe()` → `meta_analyzer.refresh_meta_background()` | Каждый sync-цикл |

### 5.2. Запуск

`bot/main.py:70`:
```python
sync_task = asyncio.create_task(sync_service.run_periodic(stop_event))
```

### 5.3. Защита от параллельного запуска

- `asyncio.Lock()` `_sync_lock` в `sync_all_once()` — **подтверждено**.
- `is_sync_running()` проверяет ` _sync_lock.locked()`.
- Admin `/sync_now` вызывает `sync_all_once()` — **будет ждать** lock, если идёт periodic sync.

### 5.4. Поведение при исключениях

| Уровень | Поведение |
|---------|-----------|
| `sync_user_battles` | CR error → return 0; Exception → log, return 0 |
| `_sync_all_once_locked` | Exception per user → log, `results[tag]=0`, **цикл продолжается** |
| `_run_sync_cycle` | Exception → `battle_error="failed"`, loop **продолжается** |
| `run_periodic` | `CancelledError` → re-raise; иные — **не ловятся на верхнем while**, но `_run_sync_cycle` ловит |

**Вывод:** задача **не умирает навсегда** после одной ошибки — **подтверждено**.

### 5.5. Retry

- На уровне sync **нет** отдельного retry для failed users; повтор — на следующем цикле (через interval).
- CR API retry — внутри `ClashRoyaleClient._request()`.

### 5.6. После перезапуска сервера

- Sync task создаётся заново; **немедленного** sync при старте **нет** — первый цикл после `interval` (или сразу при входе в loop — **первый цикл выполняется сразу** при `while not stop_event` — **да**, сразу при старте).
- In-memory battle session cache **пустой**.
- Meta cache in-memory **пустой** (перезагрузка из static/API).

### 5.7. Rate limits CR API при sync

- Между пользователями: `await asyncio.sleep(1)` (`sync_service.py:132`).
- Meta analyzer может делать **много** запросов к top players — риск 429 при большом `META_TOP_PLAYERS_SCAN`.

---

## 6. FastAPI / backend

### 6.1. Endpoints (сводка)

**Prefix `/api`** — `profile.router`, `misc.router`; **`/api/battles`** — `battles.router`; **`/api/decks`** и смежные — `decks.router`.

| Method | Path | Auth | Зависимость |
|--------|------|------|-------------|
| GET | `/api/health` | **Нет** | — |
| GET | `/api/me` | initData | `get_current_user` |
| GET | `/api/home` | initData | `get_current_user` |
| GET | `/api/profile/collection` | initData + tag | `require_linked_player` |
| GET | `/api/battles` | initData + tag + sub | `require_subscription` |
| GET | `/api/battles/{index}` | initData + tag + sub | `require_subscription` |
| GET | `/api/battles/by-time/{battle_time}` | initData + tag + sub | `require_subscription` |
| GET | `/api/decks`, `/api/decks/*` | mostly `require_linked_player` | см. `decks.py` |
| GET | `/api/winrates`, `/opponents`, `/stats`, … | `require_subscription` | `decks.py` |
| GET | `/api/search`, `/api/players/{tag}` | initData | `get_current_user` |
| GET | `/api/cards/catalog` | initData | `get_current_user` |
| GET/POST/DELETE | `/api/favorites` | initData | `get_current_user` |
| GET/PUT | `/api/settings` | initData | `get_current_user` (stub — не персистится) |
| POST | `/api/cache/clear` | initData | удаляет `battle_cache` пользователя |
| POST | `/api/sync` | initData | force refresh battles |
| GET | `/cards/*` | **Нет** (static) | StaticFiles |
| GET | `/{full_path}` | **Нет** (SPA) | если `webapp/dist` существует |

`require_admin` в `deps.py` **нигде не используется** в routes.

### 6.2. Авторизация

- **Файл:** `bot/api/auth.py` — HMAC-SHA256 validation Telegram WebApp initData (официальный алгоритм).
- **Файл:** `bot/api/deps.py` — header `X-Telegram-Init-Data`, TTL `INIT_DATA_MAX_AGE_SECONDS`, clock skew.
- Replay initData внутри TTL **допускается** (комментарий в `auth.py:33-36`).

### 6.3. CORS

```python
allow_origins=["*"], allow_credentials=True
```
(`bot/api/app.py`)

**Потенциальная проблема:** сочетание `*` + `credentials` противоречит спецификации CORS браузеров. **Невозможно подтвердить по коду** влияние на production без browser test (Vercel proxy может маскировать).

### 6.4. Обработка ошибок

- `bot/api/errors.py`: HTTPException → JSON `{message, code}`; unhandled → 500 без stack trace.
- `bot/user_errors.py`: коды `E090`–`E093`, `E010`–`E020` и др.
- Часть routes всё ещё использует `HTTPException(detail=str)` без кодов (напр. `misc.py:193` `/sync`).

### 6.5. Health / readiness

| Endpoint | Есть | Проверяет |
|----------|------|-----------|
| `/api/health` | **Да** | status ok + deckshop summary |
| Readiness (DB, CR API) | **Нет** | — |
| Liveness | **Нет** (отдельно) | health частично выполняет роль |

Health **не требует авторизации** — ожидаемо для мониторинга; раскрывает `deckshop` metadata (не секреты).

### 6.6. Утечки данных

| Риск | Статус |
|------|--------|
| Stack trace в API | **Mitigated** (`errors.py`) |
| CR API raw body пользователю | **Mitigated** (`http_error_from_clash`, user_errors) |
| `/api/search`, `/api/players/{tag}` | Возвращают **публичные** CR данные любого тега авторизованному user |
| `battle_cache` других users | **Mitigated** — фильтрация по `user.player_tag` |
| Settings PUT | Echo payload — **не сохраняется** |

### 6.7. Доступ без авторизации

**Подтверждено доступно без initData:**

- `GET /api/health`
- Static `/cards/*`
- SPA fallback (если dist собран)

Остальные `/api/*` routes требуют `get_current_user` или stricter deps.

---

## 7. WebApp / Mini App

> Анализ по локальной копии `G:/прогi/webapp` (репозиторий `Ghos_web`). Backend `.gitignore` исключает `webapp/`.

### 7.1. Получение данных Telegram

- `webapp/src/api/client.ts` → `window.Telegram?.WebApp?.initData`
- Заголовок: `X-Telegram-Init-Data`

### 7.2. Проверка initData на backend

**Да**, HMAC + TTL (`bot/api/auth.py`, `deps.py`).

### 7.3. Подделка user_id

Без знания `BOT_TOKEN` подделать валидный HMAC **не должно быть возможно** (при корректной реализации).  
Передача только `user_id` без initData → **401** (`E090`).

**Невозможно подтвердить по текущему коду** resistance к compromised `BOT_TOKEN`.

### 7.4. Подключение к API

- Production: `VITE_API_URL` пустой → запросы на same-origin `/api/*` → Vercel rewrite → `https://ghosteekcr.loca.lt/api/*` (`vercel.json`).
- Dev: `VITE_API_URL` или Vite proxy (**невозможно подтвердить** без `vite.config` — не читался в этом аудите).

### 7.5. Обработка ошибок API

- `ApiError` с кодами `E100`–`E104`, `E099`.
- User-friendly текст без упоминания PowerShell/localtunnel (**подтверждено** в `client.ts`).

### 7.6. CORS

При proxy через Vercel same-origin CORS **не применяется** к API calls из Mini App.  
Прямые запросы на `loca.lt` — возможны проблемы localtunnel reminder (**mitigated** header `Bypass-Tunnel-Reminder`).

### 7.7. Переменные окружения frontend

| Переменная | Назначение |
|------------|------------|
| `VITE_API_URL` | Base URL API (пусто = relative `/api`) |

Tunnel URL задаётся в **`vercel.json`**, не в env — смена subdomain требует redeploy Vercel.

### 7.8. Отсутствие Telegram WebApp API

`getInitData()` вернёт `""` → backend 401. **Подтверждено по коду.**

---

## 8. Конфигурация и секреты

### 8.1. Файлы

| Файл | В git | Содержимое |
|------|-------|------------|
| `.env` | **Нет** (`.gitignore`) | Runtime secrets |
| `.env.example` | **Да** | Placeholders only |

### 8.2. Переменные окружения (backend)

См. `.env.example` и `bot/config.py`. Обязательные для работы: `BOT_TOKEN`, `CLASH_ROYALE_API_KEY`.

### 8.3. Случайно закоммиченные секреты

Поиск по репозиторию: **реальных токенов не обнаружено**; только placeholders и документация.

### 8.4. Значения по умолчанию

| Переменная | Default | Риск |
|------------|---------|------|
| `clash_royale_api_key` | required, placeholder blocked | OK |
| `bot_token` | required | Warning if placeholder |
| `database_url` | local SQLite | OK dev, риск для multi-instance prod |
| `tunnel_auto_start` | `True` | На Linux no-op с warning |
| `webapp_url` | placeholder URL | Нужно задать для BotFather |

---

## 9. Деплой

### 9.1. Локально

```bash
pip install -r requirements.txt
# .env из .env.example
python -m bot.main
# webapp: npm run dev / build
```

### 9.2. VPS

| Компонент | Совместимость |
|-----------|---------------|
| Bot + FastAPI | **Да** — `python -m bot.main`, systemd |
| CR API | **Нужен** static IP или cr-proxy (`scripts/cr-proxy/`) |
| SQLite | **Да** для малой нагрузки; PG предпочтительнее |
| Localtunnel | **Не нужен** — свой домен + nginx |

**Не обнаружено:** `Dockerfile`, `Procfile`, `docker-compose` в backend repo.

### 9.3. Railway

| Аспект | Оценка |
|--------|--------|
| Запуск `python -m bot.main` | Технически возможен |
| Long polling + uvicorn в одном процессе | **Да** |
| Localtunnel auto-start | **Windows-only** — на Railway бесполезен |
| Persistent SQLite | **Риск** — ephemeral filesystem без volume |
| CR API IP whitelist | **Нужен** proxy или Railway static egress (**невозможно подтвердить** без Railway plan) |

### 9.4. Vercel (frontend)

| Аспект | Оценка |
|--------|--------|
| Static SPA | **Да** |
| API rewrites на tunnel | **Да** (`vercel.json`) |
| Backend на Vercel | **Нет** — serverful bot не для Vercel |

### 9.5. Зависимости

`requirements.txt`: aiogram, aiohttp, sqlalchemy, aiosqlite, pydantic-settings, fastapi, uvicorn.

Frontend: `webapp/package.json` (**не включён** в backend repo).

### 9.6. Последствия падения компонентов

| Комponent упал | Эффект |
|----------------|--------|
| Bot process | Нет polling, нет API, нет sync; Mini App 502/503 |
| Localtunnel | Vercel не достучится до API |
| Vercel | Mini App недоступен; бот в чате работает |
| CR API down | Sync возвращает 0; API degraded; профиль fallback на cache |
| SQLite corrupt | **CRITICAL** — весь backend data loss risk |

---

## 10. Таблица проблем

| ID | Приоритет | Файл | Проблема | Почему это проблема | Возможные последствия | Рекомендация |
|----|-----------|------|----------|---------------------|----------------------|--------------|
| A01 | **CRITICAL** | `bot/main.py` | Два инстанса бота на одном `BOT_TOKEN` | Telegram допускает один active polling/webhook | `TelegramConflictError`, бот не отвечает | Один процесс; process lock / systemd |
| A02 | **HIGH** | `bot/models/database.py` | Нет UNIQUE(`player_tag`, `battle_time`) на `battle_cache` | Check-then-insert race | Дубликаты боёv, искажение статистики | DB constraint + upsert |
| A03 | **HIGH** | `vercel.json` (webapp) | Hardcoded tunnel URL `ghosteekcr.loca.lt` | Subdomain busy / tunnel down | Mini App полностью offline | Env-based rewrite или stable VPS domain |
| A04 | **HIGH** | `bot/services/tunnel_manager.py`, `scripts/localtunnel/` | Production зависит от localtunnel (Windows) | Сервис нестабилен, subdomain global | 502, Forbidden, random URL | VPS + HTTPS + cr-proxy |
| A05 | **MEDIUM** | `bot/main.py` | Handlers `analysis`, `customization`, `subscription` не подключены | Мёртвый код / UX mismatch | Путаница при разработке; ожидания пользователей от кнопок в старых docs | Удалить или подключить; обновить docs |
| A06 | **MEDIUM** | `bot/handlers/player.py` | `_pending_link` in-memory | Теряется при рестарте | UX: пользователь «застрял» без повторного /link | FSM Redis/SQLite или persistent flag |
| A07 | **MEDIUM** | `bot/models/database.py` | Нет UNIQUE на `users.player_tag` | Один CR аккаунт → несколько TG | Конфликт данных, чужая статистика | UNIQUE или validation при link |
| A08 | **MEDIUM** | `bot/api/app.py` | CORS `*` + `credentials=True` | Spec violation | Браузерные ошибки при direct API access | Явный allowlist origins |
| A09 | **MEDIUM** | `bot/services/clash_api.py` | `has_active_subscription()` always True | Подписка не enforce | Stars/trial бессмысленны | Реализовать или убрать dead code |
| A10 | **MEDIUM** | `bot/api/routes/misc.py` | `/api/settings` PUT не сохраняет | Stub endpoint | Ложное ощущение сохранения настроек | Persist или удалить |
| A11 | **MEDIUM** | `bot/api/routes/misc.py` | `/api/cache/clear` удаляет все `battle_cache` | Destructive без confirm | Потеря истории боёv | Soft clear / partial |
| A12 | **MEDIUM** | `bot/models/database.py` | Нет Alembic; ad-hoc SQL migration | Schema drift | Ошибки при deploy на существующую БД | Alembic migrations |
| A13 | **MEDIUM** | `bot/services/meta_analyzer.py` | Много CR запросов в sync cycle | Rate limit 429 | Meta refresh fails | Throttle, cache TTL, отдельный schedule |
| A14 | **LOW** | `bot/api/deps.py` | `require_admin` unused | Dead code | — | Use for admin API or remove |
| A15 | **LOW** | `bot/handlers/subscription.py` | Stars payment router disconnected | Monetization unavailable | Нет дохода | Подключить router + menu |
| A16 | **LOW** | `bot/middleware/subscription.py` | User inject только для CallbackQuery | Message handlers не получают `user` | N/A пока routers off | Extend to Message if needed |
| A17 | **LOW** | `bot/main.py` | `api_task.cancel()` без graceful uvicorn shutdown | Abrupt connections close | Rare corrupt mid-request | lifespan shutdown hook |
| A18 | **LOW** | `tests/` | Мало integration/e2e tests | Regressions undetected | Production bugs | Expand test coverage |
| A19 | **MEDIUM** | `bot/api/routes/misc.py:193` | `/sync` HTTPException без user error code | Inconsistent errors | Raw message in some paths | `http_error()` |
| A20 | **HIGH** | Deploy architecture | Backend на домашнем ПК + tunnel | Single point of failure | Недоступность 24/7 | VPS/systemd |

---

## 11. Итоговая классификация

### 11.1. Реальные ошибки / подтверждённые проблемы (по коду)

1. **Роутеры `analysis`, `customization`, `subscription` не зарегистрированы** в `main.py` — функционал чата недоступен.
2. **Нет уникального индекса** на `(player_tag, battle_time)` — риск дубликатов боёv.
3. **`has_active_subscription()` всегда True** — проверка подписки не работает.
4. **`/api/settings` PUT** — stub, данные не сохраняются.
5. **Production coupling** с localtunnel + hardcoded URL в Vercel.

### 11.2. Потенциальные проблемы (требуют runtime / infra)

1. Race при одновременном `get_or_create_user` → IntegrityError (не обработан явно).
2. SQLite lock при высокой конкуренции.
3. CORS `*` + credentials в non-proxy сценариях.
4. Subdomain `ghosteekcr` busy на loca.lt — tunnel never ready until reclaimed.

### 11.3. Архитектурные слабые места

1. **Monolith process** — bot + API + sync + tunnel; падение одного компонента роняет всё.
2. **In-memory caches** — не масштабируются горизонтально.
3. **Два репозитория** (backend + webapp) — рассинхрон версий API/frontend.
4. **Deck builder duplicate logic** — backend + frontend local (см. `PROJECT_CONTEXT.md`).
5. **Нет migration framework**.

### 11.4. Работает нормально — менять не обязательно

1. **`ClashRoyaleClient`** — централизован, retry/backoff, safe logging, env-only token.
2. **Telegram initData validation** — HMAC + TTL (`auth.py`).
3. **Sync loop resilience** — ошибки per-user не убивают task; `_sync_lock`.
4. **User error codes** — `user_errors.py` + API error handler.
5. **Webhook delete before polling** — правильная практика.
6. **`.gitignore` для `.env`** — секреты не в repo.
7. **Graceful CR API failure on startup** — bot starts anyway.
8. **Battle sync shutdown** — `stop_event` + cancel with timeout.

---

## 12. Рекомендуемый порядок исправлений

1. **Стабилизировать production connectivity** — VPS + HTTPS, cr-proxy для CR API, убрать зависимость от localtunnel (A03, A04, A20).
2. **Гарантировать single bot instance** — systemd/supervisor, один polling (A01).
3. **UNIQUE constraint на `battle_cache(player_tag, battle_time)`** + upsert logic (A02).
4. **Решить судьбу неподключённых handlers** — удалить или подключить; синхронизировать docs (A05).
5. **Реализовать или удалить subscription enforcement** (A09, A15).
6. **UNIQUE / validation на `player_tag` при link** (A07).
7. **Alembic migrations** вместо ad-hoc ALTER (A12).
8. **Persistent pending link state** (FSM/DB) (A06).
9. **Fix `/api/settings`, `/sync` error codes, `/cache/clear` safety** (A10, A11, A19).
10. **Meta analyzer throttling** (A13).
11. **CORS allowlist** (A08).
12. **Graceful uvicorn shutdown** (A17).
13. **Расширить tests** (A18).

---

## Приложение A. Карта CR API вызовов

Все через `ClashRoyaleClient`:

| Метод | Endpoint CR |
|-------|-------------|
| `get_player` | `GET /players/{tag}` |
| `get_battlelog` | `GET /players/{tag}/battlelog` |
| `get_cards` | `GET /cards` |

Дополнительные ranking/pathoflegend запросы — в `top_players.py`, `meta_analyzer.py` (**невозможно подтвердить** exact paths без полного чтения файлов; используют тот же client).

---

## Приложение B. Невозможно подтвердить по текущему коду

- Фактическое содержимое production `.env`
- Работа tunnel/localtunnel в текущий момент
- Railway egress IP / static IP availability
- Поведение SQLite под реальной нагрузкой
- Полный `vite.config.ts` proxy rules
- CI/CD pipelines (не обнаружены в repo)
- Содержимое production `cr_bot.db`

---

*Документ создан автоматически по результатам статического аудита. Не вносит изменений в исходный код.*
