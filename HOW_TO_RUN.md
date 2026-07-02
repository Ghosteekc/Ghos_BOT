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

## 2. Развёртывание на Railway

### Способ 1: Через GitHub

1. Запушьте репозиторий на GitHub.
2. Создайте новый проект на Railway → **Deploy from GitHub** → выберите ваш репозиторий.
3. Railway автоматически подхватит `railway.json`.

### Способ 2: Через Railway CLI

```bash
npm install -g @railway/cli
railway login
railway init
railway up
```

### Переменные окружения на Railway

В разделе **Variables** Railway добавьте:

| Имя | Значение | Обязательно |
|---|---|---|
| `BOT_TOKEN` | Токен бота от @BotFather | ✅ |
| `CLASH_ROYALE_API_KEY` | Ключ Clash Royale API | ✅ |
| `ADMIN_TELEGRAM_ID` | Ваш Telegram ID | опционально |
| `WEBAPP_URL` | `https://<ваш-проект>.up.railway.app` | ✅ |
| `TRIAL_DAYS` | `3` | опционально |
| `SUBSCRIPTION_PRICE_STARS` | `250` | опционально |

> **Важно:** `WEBAPP_URL` должен быть HTTPS URL вашего Railway проекта (например, `https://ghosteek-cr-assistant.up.railway.app`). Telegram WebApp требует HTTPS.

### Как узнать URL Railway

После деплоя в разделе **Settings → Domains** вы увидите assigned domain, например:
```
https://ghosteek-cr-assistant.up.railway.app
```

Именно его укажите в `WEBAPP_URL`.

### Проверка деплоя

1. Откройте бота в Telegram → `/start`
2. Нажмите «📱 Открыть приложение»
3. Мини-приложение должно открыться внутри Telegram

### Health check

Railway будет проверять `/api/health` каждые 30 секунд. Если бот не отвечает, Railway перезапустит контейнер.

---

## 3. Развёртывание на GitHub Pages (альтернатива Railway)

Если вы хотите разместить frontend на GitHub Pages, а backend на Railway:

### Frontend на GitHub Pages

1. В `webapp/vite.config.ts` установите `base: "/<имя-репо>/"`.
2. Соберите frontend:
   ```bash
   cd webapp
   npm install
   npm run build
   ```
3. Запушьте содержимое `webapp/dist/` в ветку `gh-pages` или используйте GitHub Actions для деплоя.

### Backend на Railway

- Развёртывайте Python-часть на Railway как обычно.
- Укажите в `WEBAPP_URL` ссылку на GitHub Pages.
- Добавьте в CORS (в `bot/api/app.py`) ваш GitHub Pages URL.

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
├── railway.json           # Конфигурация Railway
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
| Mini App не открывается Railway | Проверьте `WEBAPP_URL` — должен быть `https://...up.railway.app` |
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
