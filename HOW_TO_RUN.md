# Как запускать Ghosteek CR Assistant + Mini App

## Предварительные требования

- Python 3.10+
- Node.js 18+
- Telegram бот токен (от @BotFather)
- Clash Royale API ключ (от https://developer.clashroyale.com)
- Git

---

## 1. Локальный запуск

### Клонирование и виртуальное окружение

```bash
git clone <repo_url>
cd ss
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### Переменные окружения

Создайте `.env` в корне проекта (скопируйте из `.env.example`):

```env
BOT_TOKEN=ваш_telegram_bot_token
CLASH_ROYALE_API_KEY=ваш_cr_api_key
ADMIN_TELEGRAM_ID=ваш_telegram_id
WEBAPP_URL=http://localhost:5173
```

Для локальной разработки Mini App используйте `WEBAPP_URL=http://localhost:5173` (Vite dev server).

### Запуск backend (bot + FastAPI)

```bash
python -m bot.main
```

Бот запустится на polling. FastAPI сервер будет доступен на `http://localhost:8080`.

### Запуск frontend (Mini App) — вариант A (dev сервер)

```bash
cd webapp
npm install
npm run dev
```

Frontend будет на `http://localhost:5173`. API запросы проксируются на `localhost:8080`.

### Запуск frontend — вариант B (сборка + FastAPI)

```bash
cd webapp
npm install
npm run build
cd ..
python -m bot.main
```

FastAPI будет раздавать собранный frontend из `webapp/dist/` на `http://localhost:8080`.

---

## 2. Продакшен: GitHub + Vercel + localtunnel

Код хранится на GitHub: [Ghosteekc/Ghos_BOT](https://github.com/Ghosteekc/Ghos_BOT).

| Компонент | Где работает |
|-----------|--------------|
| **Backend** (бот + API) | Ваш ПК или VPS: `python -m bot.main` |
| **HTTPS для API** | [localtunnel](scripts/localtunnel/README.md) |
| **Mini App** | [Vercel](https://vercel.com) (отдельный репозиторий `webapp`) |
| **Clash Royale API** | Прямой доступ или VPS-прокси ([cr-proxy](scripts/cr-proxy/README.md)) |

### Обновление кода на GitHub

```bash
git add .
git commit -m "описание изменений"
git push origin main
```

После пуша перезапустите бота на машине, где он работает:

```bash
python -m bot.main
```

### Переменные окружения (.env)

| Имя | Значение | Обязательно |
|---|---|---|
| `BOT_TOKEN` | Токен бота от @BotFather | ✅ |
| `CLASH_ROYALE_API_KEY` | Ключ Clash Royale API | ✅ |
| `WEBAPP_URL` | HTTPS URL Mini App на Vercel | ✅ |
| `ADMIN_TELEGRAM_ID` | Ваш Telegram ID | опционально |
| `TRIAL_DAYS` | `3` | опционально |
| `SUBSCRIPTION_PRICE_STARS` | `250` | опционально |

На Vercel в переменных проекта `webapp`:

1. **`VITE_API_URL` — оставьте пустым** (удалите или очистите значение).
2. URL туннеля укажите в **`webapp/vercel.json`** → `rewrites` → `destination` (например `https://ghosteekcr.loca.lt/api/:path*`).
3. После смены subdomain туннеля — обновите `vercel.json` и **Redeploy**.

Так друзья не ходят на `loca.lt` напрямую и не видят **Forbidden** (защита localtunnel для новых IP).

### Проверка деплоя

1. `curl -H "Bypass-Tunnel-Reminder: true" https://ВАШ-URL.loca.lt/api/health` → `{"status":"ok"}`
2. Откройте бота в Telegram → `/start` → «📱 Открыть приложение»
3. Проверьте уровень коллекции в профиле

### Health check

Туннель проксирует `/api/health`. Скрипт `start-tunnel.ps1` перезапускает localtunnel при обрыве.

---

## 4. Структура проекта

```
F:\ss
├── bot/                    # Python backend (aiogram + FastAPI)
│   ├── main.py             # Точка входа: bot + API + sync
│   ├── config.py           # Pydantic Settings
│   ├── api/                # FastAPI routes
│   ├── handlers/           # Aiogram handlers
│   ├── services/           # Бизнес-логика (API, аналитика, синхронизация)
│   ├── models/             # SQLAlchemy модели
│   ├── keyboards/          # Telegram клавиатуры
│   └── middleware/         # Aiogram middleware
├── webapp/                 # Mini App (React + Vite)
│   ├── src/
│   │   ├── pages/          # Страницы приложения
│   │   ├── api/            # API client для фронтенда
│   │   └── components/     # Переиспользуемые компоненты
│   ├── dist/               # Сборка (игнорируется в git)
│   └── package.json
├── requirements.txt        # Python зависимости
├── build.sh               # Скрипт сборки
├── .env.example           # Шаблон переменных окружения
└── HOW_TO_RUN.md          # Этот файл
```

---

## 5. Частые проблемы

| Проблема | Решение |
|---|---|
| `ModuleNotFoundError: No module named 'uvicorn'` | `pip install -r requirements.txt` |
| `ModuleNotFoundError: No module named 'fastapi'` | `pip install -r requirements.txt` |
| Бот не запускается, ошибка `ObjectNotExecutableError` | Исправлена в текущей версии, обновите `bot/models/database.py` |
| Mini App не открывается | Проверьте `WEBAPP_URL` на Vercel и что туннель к API жив |
| Mini App не открывается локально | Убедитесь, что frontend запущен (`npm run dev`) и `WEBAPP_URL=http://localhost:5173` |
| API ошибки в Mini App | Проверьте, что пользователь привязал тег (`/link`) и есть активная подписка (`/subscribe`) |
| Clash Royale API 403 `invalidIp` | Добавьте IP сервера в настройки ключа на developer.clashroyale.com или используйте ключ без IP-ограничения |

---

## 6. Переменные окружения (полный список)

| Имя | Описание | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | Токен Telegram бота | — |
| `CLASH_ROYALE_API_KEY` | Ключ Clash Royale API | — |
| `CLASH_ROYALE_API_BASE` | Базовый URL API | `https://api.clashroyale.com/v1` |
| `DATABASE_URL` | URL базы данных | `sqlite+aiosqlite:///./cr_bot.db` |
| `TRIAL_DAYS` | Дней пробного периода | `3` |
| `SUBSCRIPTION_PRICE_STARS` | Цена подписки в Stars | `250` |
| `SYNC_INTERVAL_MINUTES` | Интервал синхронизации боёв | `60` |
| `ADMIN_TELEGRAM_ID` | ID админа для /sync_now | — |
| `WEBAPP_URL` | URL Mini App (HTTPS!) | `https://your-domain.com` |
| `SUPPORT_USERNAME` | Юзернейм поддержки (без @) | — |
| `API_HOST` | Хост FastAPI | `0.0.0.0` |
| `API_PORT` | Порт FastAPI | `8080` |
| `VITE_API_URL` | Базовый URL API для фронтенда | пусто (same-origin) |
