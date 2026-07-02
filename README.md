# Ghosteek CR Assistant

Telegram-бот + Mini App для анализа Clash Royale с подпиской. Вход по тегу игрока.

## Архитектура

| Компонент | Назначение |
|-----------|------------|
| **Чат-бот** | `/link`, `/profile`, `/subscribe`, поддержка, кнопка Mini App |
| **Mini App** (React) | Анализ боёв, винрейт, соперники, контр-колоды, кастомизация, синергии |
| **FastAPI** | REST API с авторизацией через Telegram `initData` |

## Возможности (подписка, в Mini App)

| Функция | Описание |
|---------|----------|
| Анализ боёв | Разбор побед/поражений, матчап, счётчики |
| Колоды соперников | Колоды из последних боёв API |
| Винрейт колод | Статистика побед по каждой колоде |
| Контр-колоды | Подбор колоды под конкретного соперника |
| Кастомизация | Оптимизация колоды под арену и любимые карты |
| Синергии | Сборка колоды вокруг ваших частых карт |
| Статистика | Агрегаты по сохранённым боям |

## Быстрый старт

### 1. Получите ключи

- **Telegram Bot Token** — [@BotFather](https://t.me/BotFather)
- **Clash Royale API Key** — [developer.clashroyale.com](https://developer.clashroyale.com)

> Для CR API укажите IP сервера в настройках ключа. Для локальной разработки — ngrok или VPS.

### 2. Настройка бэкенда

```bash
cd /path/to/ss
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Заполните BOT_TOKEN, CLASH_ROYALE_API_KEY, WEBAPP_URL, SUPPORT_USERNAME
```

### 3. Сборка Mini App

```bash
cd webapp
npm install
npm run build
```

### 4. Запуск

```bash
python -m bot.main
```

Бот (polling) и API запускаются вместе. API по умолчанию: `http://0.0.0.0:8080`.

### 5. Mini App в Telegram (HTTPS обязателен)

1. Пробросьте порт через туннель, например:
   ```bash
   ngrok http 8080
   ```
2. Укажите HTTPS-URL в `.env`:
   ```
   WEBAPP_URL=https://xxxx.ngrok-free.app
   ```
3. В [@BotFather](https://t.me/BotFather) → Bot Settings → Menu Button / Web App — тот же URL.
4. Перезапустите бота.

**Локальная разработка фронтенда** (без Telegram):

```bash
cd webapp
npm run dev
```

Vite проксирует `/api` на `localhost:8080`. Для теста API без Telegram initData потребуется открыть через бота.

## Команды бота (чат)

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню |
| `/link #ТЕГ` | Привязать аккаунт Clash Royale |
| `/profile` | Профиль игрока |
| `/subscribe` | Подписка / пробный период |
| `/help` | Справка |
| `/sync_now` | Синхронизация боёв (админ) |

## Подписка

- **Пробный период** — 3 дня бесплатно (один раз)
- **Платная подписка** — Telegram Stars (250 ⭐ / 30 дней)

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен Telegram-бота |
| `CLASH_ROYALE_API_KEY` | Ключ CR API |
| `WEBAPP_URL` | HTTPS URL Mini App |
| `SUPPORT_USERNAME` | Username поддержки (без @) |
| `API_HOST` / `API_PORT` | Хост и порт FastAPI |
| `ADMIN_TELEGRAM_ID` | ID админа для `/sync_now` |

## Структура проекта

```
bot/
├── main.py              # Бот + API + sync
├── api/                 # FastAPI (REST + статика webapp/dist)
├── handlers/            # Telegram-обработчики (чат)
├── services/            # CR API, анализ, battle_service
├── models/database.py   # SQLite
└── middleware/
webapp/                  # React Mini App (Vite + TypeScript)
```

## API (Mini App)

Все эндпоинты (кроме `/api/health`) требуют заголовок `X-Telegram-Init-Data`.

```
GET /api/me
GET /api/battles
GET /api/battles/{index}
GET /api/winrates
GET /api/opponents
GET /api/opponents/{index}/counter
GET /api/customize
GET /api/synergy
GET /api/stats
```
