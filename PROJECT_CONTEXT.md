# PROJECT_CONTEXT — Ghosteek CR Assistant

Документ описывает **текущее состояние** проекта на момент анализа: архитектуру, frontend, backend, API, Telegram-бота и логику генерации колод. Предназначен для быстрого онбординга и работы с AI-ассистентами.

---

## 1. Обзор продукта

**Ghosteek CR Assistant** — Telegram-бот + Telegram Mini App (WebApp) для игроков Clash Royale.

| Функция | Где реализовано |
|---------|-----------------|
| Привязка аккаунта по тегу | Чат-бот + API |
| Синхронизация и разбор боёв | Backend + CR API |
| Статистика, винрейт, соперники | Mini App + API |
| Meta / мои / арена / топ колоды | Mini App + API |
| **Конструктор колод (4 → 8 карт)** | **Mini App (локально)** + дублирующий API на backend |
| Сравнение колод | Mini App + API |
| Ghøsteek Deck Passport (анализ колоды) | Mini App (локально) |
| Рекомендации по прокачке (арены 1–32) | Mini App (локально) |
| Избранные колоды | Mini App + API + SQLite |
| Подписка (trial / Telegram Stars) | Backend + middleware |

---

## 2. Структура репозиториев

Проект физически состоит из **двух связанных частей**:

| Часть | Путь (локально) | GitHub | Назначение |
|-------|-----------------|--------|------------|
| **Backend + бот** | `G:/проги/ss/` | [Ghosteekc/Ghos_BOT](https://github.com/Ghosteekc/Ghos_BOT) | Python: aiogram, FastAPI, SQLite, CR API |
| **Mini App** | `G:/проги/webapp/` | [Ghosteekc/Ghos_web](https://github.com/Ghosteekc/Ghos_web) | React + Vite + TypeScript |

Скрипт `scripts/generate_deck_builder_data.py` пишет данные **в оба места**:

- `bot/data/cards.json`, `bot/data/decks.json`
- `../webapp/src/data/cards.json`, `../webapp/src/data/decks.json`

FastAPI при сборке может раздавать `webapp/dist/` (если собран), но в продакшене Mini App обычно на **Vercel**, API — на ПК/VPS через **HTTPS-туннель**.

---

## 3. Архитектура (высокий уровень)

```
┌─────────────────────────────────────────────────────────────────┐
│                     Telegram (пользователь)                    │
└────────────┬───────────────────────────────┬────────────────────┘
             │ polling (чат)                  │ WebApp (Mini App)
             ▼                                ▼
┌────────────────────────┐          ┌─────────────────────────────┐
│  bot/main.py           │          │  webapp (React SPA)         │
│  aiogram Dispatcher    │          │  Vercel / Vite dev :5173    │
│  handlers/*            │          │  src/pages, components, …   │
└───────────┬────────────┘          └──────────────┬──────────────┘
            │                                      │
            │         ┌──────────────────────────────┘
            │         │  X-Telegram-Init-Data
            ▼         ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI (bot/api/app.py)  :8080                                 │
│  routes: profile, battles, decks, misc                           │
└────────────┬───────────────────────────────┬────────────────────┘
             │                               │
             ▼                               ▼
┌────────────────────────┐       ┌───────────────────────────────┐
│  bot/services/*        │       │  SQLite (cr_bot.db)           │
│  clash_api, battle_*,  │       │  users, subscriptions,        │
│  deck_*, card_matchups │       │  battle_cache, favorite_decks │
└────────────┬───────────┘       └───────────────────────────────┘
             │
             ▼
┌────────────────────────┐       ┌───────────────────────────────┐
│  Clash Royale API      │       │  Локальные данные             │
│  (+ опц. VPS proxy)    │       │  cards.json, decks.json,      │
└────────────────────────┘       │  deckshop_counters.py         │
                                 └───────────────────────────────┘
```

---

## 4. Backend (`bot/`)

### 4.1 Точка входа

**Файл:** `bot/main.py`  
**Команда:** `python -m bot.main`

При старте:

1. `init_db()` — SQLite через SQLAlchemy async
2. Проверка CR API (`ClashRoyaleClient.get_cards()`)
3. aiogram `Bot` + `Dispatcher` + `SubscriptionMiddleware`
4. Роутеры: `start`, `player`, `support`, `admin`
5. Фон: `sync_service.run_periodic()` — периодическая синхронизация боёв
6. Фон: uvicorn FastAPI на `API_HOST:API_PORT` (по умолчанию `0.0.0.0:8080`)
7. `dp.start_polling(bot)`

**Не подключены в `main.py`**, но существуют: `handlers/subscription.py`, `handlers/customization.py`, `handlers/analysis.py`.

### 4.2 Конфигурация

**Файл:** `bot/config.py` (pydantic-settings из `.env`)

Ключевые переменные: `BOT_TOKEN`, `CLASH_ROYALE_API_KEY`, `CLASH_ROYALE_API_BASE`, `DATABASE_URL`, `WEBAPP_URL`, `API_HOST`, `API_PORT`, `SYNC_INTERVAL_MINUTES`, `TRIAL_DAYS`, `SUBSCRIPTION_PRICE_STARS`, `ADMIN_TELEGRAM_ID(S)`, `META_*`.

Шаблон: `.env.example`. Инструкции: `HOW_TO_RUN.md`.

### 4.3 FastAPI

**Файл:** `bot/api/app.py`

- CORS `*`
- Роутеры: `profile`, `battles`, `decks`, `misc`
- Статика: `/cards` → `bot/static/cards/`
- SPA fallback: `webapp/dist/index.html` (если собран)

**Авторизация:** `bot/api/auth.py` — HMAC-проверка Telegram WebApp `initData`.  
**Зависимости:** `bot/api/deps.py` — `get_current_user`, `require_linked_player`, `require_subscription`.

### 4.4 Модели БД

**Файл:** `bot/models/database.py`

| Таблица | Назначение |
|---------|------------|
| `users` | Telegram ID, player_tag, arena, trophies |
| `subscriptions` | trial / active / expires_at |
| `card_preferences` | частота карт в боях |
| `battle_cache` | сохранённые бои + JSON analysis |
| `favorite_decks` | `deck_key` = 8 карт через запятую (порядок как при сохранении) |

### 4.5 Основные сервисы

| Сервис | Файл | Роль |
|--------|------|------|
| CR API клиент | `clash_api.py` | Запросы к Supercell API, подписки |
| Синхронизация | `sync_service.py` | Периодический fetch боёв в `battle_cache` |
| Разбор боя | `battle_service.py`, `battle_report.py` | Анализ матчапа, контры |
| Инсайты | `battle_insights.py` | Паттерны поражений |
| Meta / арена | `meta_analyzer.py`, `arena_decks.py`, `meta_decks.py` | Meta-колоды, арена |
| Топ игроков | `top_players.py` | Legend Path |
| Случайная колода | `random_deck.py`, `rofl_decks.py` | Random / rofl |
| Контры / кастом | `counter_engine.py`, `deck_improver.py` | Counter-deck, customize, synergy API |
| **Deck builder** | `deck_builder/` | Генерация 4→8 (Python) |
| Конструктор API | `deck_constructor.py` | Адаптер для `POST /decks/constructor` |
| Сравнение | `deck_compare.py` | Matchup + synergy notes |
| Matchups | `card_matchups.py` | Контры/синергии из DeckShop snapshot |
| Коллекция | `player_collection.py` | Уровни, evo, hero, collection_level |
| Карты | `card_data.py`, `card_registry.py`, `card_names_ru.py` | META, иконки, RU имена |

### 4.6 Данные

| Файл | Содержимое |
|------|------------|
| `bot/data/cards.json` | elixir, type, roles (~114 карт) |
| `bot/data/decks.json` | ~12 meta-шаблонов + `synergyPairs` |
| `bot/data/deckshop_counters.py` | Снимок deckshop.pro: counters + synergy_offense (~27k строк) |
| `bot/services/card_data.py` | `CARD_META`, `WIN_CONDITIONS`, ручные контры |
| `bot/services/meta_decks.py` | Fallback meta-колоды |

Обновление DeckShop: `scripts/scrape_deckshop_counters.py` (+ `deckshop_add_anticounters.py`).

---

## 5. API (REST)

Все эндпоинты под `/api`, кроме **`GET /api/health`**, требуют заголовок **`X-Telegram-Init-Data`**.

### Profile (`bot/api/routes/profile.py`)

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/me` | Профиль игрока |
| GET | `/api/profile/collection` | Коллекция карт |
| GET | `/api/home` | Dashboard |
| GET | `/api/health` | Health check |

### Battles (`bot/api/routes/battles.py`)

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/battles` | Список боёв |
| GET | `/api/battles/{index}` | Детали по индексу |
| GET | `/api/battles/by-time/{battle_time}` | Детали по timestamp |

### Decks & analytics (`bot/api/routes/decks.py`)

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/decks` | Meta / mine колоды |
| GET/POST | `/api/decks/mine/stats` | Статистика своей колоды |
| GET | `/api/decks/arena` | Популярные колоды арены |
| POST | `/api/decks/constructor` | Генерация из 4 карт (backend) |
| POST | `/api/decks/compare` | Сравнение колод |
| GET | `/api/decks/top-players` | Топ игроков |
| GET | `/api/decks/random` | Случайная / rofl колода |
| GET | `/api/insights` | Инсайты по поражениям |
| GET | `/api/winrates` | Винрейт колод |
| GET | `/api/opponents` | Соперники |
| GET | `/api/opponents/{index}/counter` | Контр-колода |
| GET | `/api/customize` | Кастомизация под арену |
| GET | `/api/synergy` | Синергии вокруг частых карт |
| GET | `/api/stats` | Расширенная статистика |
| GET | `/api/recommendations` | Рекомендации (backend) |

### Misc (`bot/api/routes/misc.py`)

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/cards/catalog` | Каталог карт (иконки, evo, hero, RU) |
| GET | `/api/search` | Поиск по тегу |
| GET | `/api/players/{tag}` | Превью игрока |
| GET/POST/DELETE | `/api/favorites` | Избранные колоды |
| GET/PUT | `/api/settings` | Настройки |
| POST | `/api/sync` | Принудительная синхронизация |
| POST | `/api/cache/clear` | Очистка кэша |

---

## 6. Telegram-бот (чат)

**Handlers (подключены):**

| Файл | Назначение |
|------|------------|
| `handlers/start.py` | `/start`, меню, кнопка Mini App |
| `handlers/player.py` | `/link`, `/profile` |
| `handlers/support.py` | Поддержка |
| `handlers/admin.py` | `/sync_now` и админ-команды |

**Middleware:** `middleware/subscription.py` — inject user/sub_service в callback handlers.

**Команды (из README):** `/start`, `/link #TAG`, `/profile`, `/subscribe`, `/help`, `/sync_now`.

Подписка: trial (~3 дня / 30 дней в config), оплата Telegram Stars.

---

## 7. Frontend (Mini App)

### 7.1 Стек и сборка

- React 18, TypeScript, Vite, Tailwind, React Router v6, Framer Motion, Recharts
- **Dev:** `npm run dev` → `:5173`, proxy `/api` → `localhost:8080` (`vite.config.ts`)
- **Prod:** Vercel, `vercel.json` проксирует `/api/*` → `https://ghosteekcr.loca.lt/api/*`

### 7.2 Структура `webapp/src/`

| Путь | Назначение |
|------|------------|
| `App.tsx` | Lazy routes |
| `layout/Layout.tsx` | Shell, Telegram safe area, providers |
| `layout/Sidebar.tsx` | Навигация |
| `pages/` | Страницы приложения |
| `components/` | UI, карты, decks, analytics |
| `api/client.ts` | HTTP + cache + retry |
| `api/cache.ts` | in-memory + localStorage |
| `hooks/` | Telegram, refresh, favorites, catalog |
| `services/deckBuilder/` | **Локальный** генератор колод |
| `services/constructorAdapter.ts` | Связка конструктора с UI |
| `analytics/deckPassport/` | Ghøsteek Deck Passport |
| `components/analytics/recommendations/` | Рекомендации по аренам |
| `data/cards.json`, `decks.json` | Статические данные builder |

### 7.3 Маршруты

| Route | Страница |
|-------|----------|
| `/` | Профиль |
| `/profile/cards`, `/profile/mastery` | Коллекция, мастерство |
| `/analytics` | Аналитика (5 вкладок) |
| `/decks` | Колоды (meta, top, mine, arena, constructor, random) |
| `/decks/compare` | Сравнение колод |
| `/decks/mine/stats` | Статистика «моих» колод |
| `/battles`, `/battles/:index`, `/battles/t/:time` | Бои |
| `/favorites` | Избранное |
| `/search`, `/player/:tag` | Поиск |
| `/settings` | Настройки |

### 7.4 Telegram WebApp

- SDK в `index.html`
- `useTelegram()` — initData, openLink, haptics, alerts
- Safe area CSS vars в `Layout.tsx` (`--tg-content-safe-*`)
- Каждый API-запрос: `X-Telegram-Init-Data`

### 7.5 Кэширование (frontend)

`api/cache.ts`: TTL для profile, battles, stats, catalog, favorites и т.д.  
Страницы инициализируют state из `cacheGet()` для мгновенного UI.

### 7.6 Избранное

- `FavoriteDecksProvider` — глобальный контекст
- `FavoriteDeckButton` — жёлтая ★ для колод в избранном
- Ключ на клиенте: `normalizeDeckKey` (sorted join имён)
- Backend: `deck_key` = `",".join(cards)` в порядке сохранения

---

## 8. Логика генерации колод

Реализована **дважды** (Python backend + TypeScript frontend) с одинаковой идеей. **UI конструктора использует только клиентскую версию.**

### 8.1 Вход

- Ровно **4 уникальные карты** (ядро)
- Слоты конструктора: 0,2 — evo; 1 — hero; 3 — обычная (`ConstructorPanel.tsx`)

### 8.2 Pipeline (7 шагов)

| Шаг | Действие | Backend | Frontend |
|-----|----------|---------|----------|
| 1 | Валидация ядра | `build_multiple_decks` | `buildMultipleDecks` |
| 2 | Загрузка данных | `DeckDatabase` / `loader.py` | `database.ts` → json |
| 3 | Архетип | `_detect_archetype` | `detectArchetype` |
| 4 | Поиск шаблонов | `_rank_similar_decks` | `rankSimilar` |
| 5 | Fillers из шаблона | `_fillers_from_template` | `fillersFromTemplate` |
| 6 | Финализация / баланс | `_finalize_deck` | `finalizeDeck` |
| 7 | Несколько вариантов | до 6, dedupe | до 6, dedupe |

**Файлы:**

- Backend: `bot/services/deck_builder/builder.py`, `constants.py`, `loader.py`
- Frontend: `webapp/src/services/deckBuilder/builder.ts`, `balance.ts`, `synergy.ts`, `constants.ts`

### 8.3 Scoring шаблонов

Веса (frontend `constants.ts` / backend `constants.py`):

- `WEIGHT_CARD_MATCH` (25) — overlap с ядром
- `WEIGHT_ARCHETYPE` (20)
- `WEIGHT_ELIXIR` (15) — близость avg elixir; штраф для дешёвого ядра
- `WEIGHT_SYNERGY` (15)
- `WEIGHT_POPULARITY` (5)

`GENERIC_CARDS` (Log, Zap, Skeletons, …) дают меньший вес overlap.

### 8.4 Баланс колоды (`balanceIssues`)

Обязательные роли / ограничения:

- win condition (ровно 1, `MAX_WINS`)
- big_spell + small_spell
- spells ≤ 3
- air_defense ≥ 2
- anti_tank, defensive, anti_swarm
- elixir в bounds архетипа (`ARCHETYPE_ELIXIR`)

**Frontend дополнения:** `enforceCriticalBalance` — замена слабых filler'ов на Knight/Valkyrie/Ice Golem и anti-tank swarm на дешёвых колодах; `CRITICAL_BALANCE_ROLES`, `CHEAP_DECK_ANCHORS`.

### 8.5 Синергия

**Правила (frontend `synergy.ts`, backend `card_matchups.is_valid_synergy_pair`):**

- Синергия только если в паре есть **атакующая карта** (win condition)
- Запрещены пары: дух ↔ заклинание/здание, заклинание ↔ здание
- Источники score: `KNOWN_SYNERGY`, `decks.json synergyPairs`, DeckShop

**Отображение:** `synergyNotes()` — пары с score ≥ `SYNERGY_STRONG` (88).

**Сравнение колод:** `calculate_deck_synergy()` — уникальные неупорядоченные пары (без дублей A+B / B+A).

### 8.6 Архетипы

Cycle, Log Bait, Beatdown, Control, Siege, Lava, Royal Giant, Bridge Spam, Graveyard, Split Lane, Meta, …

Якоря: `ARCHETYPE_ANCHORS`, primary win: `ARCHETYPE_PRIMARY_WIN`.

### 8.7 Прочие режимы генерации (только backend)

| Режим | Сервис | API |
|-------|--------|-----|
| Контр-колода | `counter_engine.suggest_counter_deck` | `/opponents/{i}/counter` |
| Customize | `counter_engine.customize_deck_for_arena` | `/customize` |
| Synergy deck | `counter_engine.build_synergy_deck` | `/synergy` |
| Random / rofl | `random_deck` | `/decks/random` |

---

## 9. Ghøsteek Deck Passport (локально)

**Путь:** `webapp/src/analytics/deckPassport/`

Анализ полной 8-карточной колоды без API:

- Ghosteek Score, звёзды, метрики (attack, defense, cycle, antiAir, …)
- Архетип, стиль, роли, практичность, сложность, матчапы
- Открывается из `DecksPage` → кнопка «Анализ»

Использует `balanceIssues`, `deckSynergyScore` из deckBuilder.

---

## 10. Рекомендации по прокачке (локально)

**Путь:** `webapp/src/components/analytics/recommendations/`

- `arenaRecommendations.ts` — арены 1–32, RU названия, пороги кубков, recommended level (29–30 → 15+, 31–32 → 16+)
- `recommendationEngine.ts` — сравнение с `player_collection`
- Данные: `api.getProfile()`, `api.getPlayerCollection()`

---

## 11. Деплой и окружения

| Компонент | Где | Как |
|-----------|-----|-----|
| Backend | ПК / VPS | `python -m bot.main` |
| HTTPS для API | localtunnel | `scripts/localtunnel/` |
| Mini App | Vercel | push в `Ghos_web` |
| CR API | Supercell / VPS proxy | `scripts/cr-proxy/` |

**Локально:** backend `:8080`, frontend `:5173` (proxy).  
**Альтернатива:** `npm run build` в webapp → FastAPI раздаёт `dist/`.

Подробно: `HOW_TO_RUN.md`.

---

## 12. Скрипты (`scripts/`)

| Скрипт | Назначение |
|--------|------------|
| `generate_deck_builder_data.py` | cards.json + decks.json → bot + webapp |
| `scrape_deckshop_counters.py` | DeckShop → deckshop_counters.py |
| `deckshop_add_anticounters.py` | Постобработка counters |
| `build-webapp.sh` | npm build webapp |
| `localtunnel/` | HTTPS туннель (localtunnel) |
| `cr-proxy/` | Nginx proxy для CR API |

---

## 13. Ключевые файлы (шпаргалка)

### Backend

```
bot/main.py                          # entry point
bot/config.py                        # settings
bot/api/app.py                       # FastAPI app
bot/api/routes/decks.py              # decks API
bot/services/deck_builder/builder.py # генератор 4→8
bot/services/deck_constructor.py     # API adapter
bot/services/card_matchups.py        # контры/синергии
bot/services/deck_compare.py         # сравнение колод
bot/services/player_collection.py    # коллекция
bot/data/deckshop_counters.py        # DeckShop snapshot
bot/models/database.py               # ORM
```

### Frontend

```
webapp/src/App.tsx                   # routes
webapp/src/api/client.ts             # API client
webapp/src/pages/DecksPage.tsx       # колоды + constructor tab
webapp/src/components/decks/ConstructorPanel.tsx
webapp/src/services/constructorAdapter.ts
webapp/src/services/deckBuilder/builder.ts
webapp/src/services/deckBuilder/balance.ts
webapp/src/services/deckBuilder/synergy.ts
webapp/src/analytics/deckPassport/DeckAnalyzer.ts
webapp/src/components/analytics/recommendations/
webapp/vercel.json                   # prod API proxy
```

---

## 14. Важные особенности / технический долг

1. **Дублирование deck builder** — Python и TypeScript должны синхронизироваться через общие JSON; логика баланса/синергии может расходиться.
2. **Конструктор в UI не вызывает** `POST /api/decks/constructor` — только локальный `buildConstructorDecksLocal`.
3. **Handlers** `subscription`, `customization`, `analysis` не подключены в `main.py`.
4. **Production API** зависит от localtunnel URL в `vercel.json` (нужно обновлять при смене туннеля).
5. **Избранное:** клиент сравнивает колоды по sorted key; backend хранит порядок карт в `deck_key`.
6. **DeckShop** — offline snapshot; для обновления нужен ручной scrape.

---

## 15. Связанная документация

- `README.md` — краткий обзор и команды бота
- `HOW_TO_RUN.md` — локальный и продакшен запуск
- `scripts/localtunnel/README.md` — HTTPS туннель
- `scripts/cr-proxy/README.md` — прокси CR API

---

*Документ сгенерирован по результатам анализа кодовой базы. При изменении архитектуры обновляйте этот файл.*
