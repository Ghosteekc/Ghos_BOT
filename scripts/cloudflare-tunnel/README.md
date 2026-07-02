# Cloudflare Tunnel для локального API

## Почему «простая» команда не работает

По умолчанию `cloudflared` пробует **QUIC (UDP)** и **IPv6**. На многих сетях (провайдер, роутер, VPN) это падает с ошибками подключения.

Рабочий вариант для вашей машины:

```powershell
cloudflared tunnel --url http://127.0.0.1:8080 --protocol http2 --edge-ip-version 4 --ha-connections 1
```

| Флаг | Зачем |
|------|--------|
| `--protocol http2` | TCP/443 вместо QUIC/UDP |
| `--edge-ip-version 4` | только IPv4 |
| `--ha-connections 1` | одно соединение, меньше сбоев |
| `127.0.0.1` | иногда надёжнее, чем `localhost` |

---

## Quick Tunnel (временный URL, меняется при перезапуске)

```powershell
# Терминал 1 — backend
cd G:\проги\ss
.venv\Scripts\activate
python -m bot.main

# Терминал 2 — туннель
cloudflared tunnel --url http://127.0.0.1:8080 --protocol http2 --edge-ip-version 4 --ha-connections 1
```

В выводе будет строка вида:

```
https://something-random.trycloudflare.com
```

Проверка:

```powershell
curl https://something-random.trycloudflare.com/api/health
```

**Минус:** URL новый после каждого перезапуска → обновить `VITE_API_URL` на Vercel → **Redeploy**.

Ошибка **1033 / 530** = туннель не запущен или URL уже старый.

---

## Named Tunnel (постоянный URL, нужен домен в Cloudflare)

Quick Tunnel **нельзя** сделать постоянным. Для стабильного адреса (`https://api.example.com`) — именованный туннель.

### 1. Логин (один раз)

```powershell
cloudflared tunnel login
```

Выберите домен в браузере. Появится `%USERPROFILE%\.cloudflared\cert.pem`.

### 2. Создать туннель

```powershell
cloudflared tunnel create ghosteek-cr-api
```

### 3. DNS

```powershell
cloudflared tunnel route dns ghosteek-cr-api api.example.com
```

### 4. Конфиг

Скопируйте `config.example.yml` → `%USERPROFILE%\.cloudflared\config.yml` и подставьте Tunnel ID, домен, путь к credentials.

В конфиге уже прописаны `protocol: http2`, `edge-ip-version: 4`, `ha-connections: 1`.

### 5. Запуск (с теми же флагами, что и Quick Tunnel)

```powershell
cloudflared tunnel --protocol http2 --edge-ip-version 4 --ha-connections 1 run ghosteek-cr-api
```

Или только из конфига (если поля `protocol` / `edge-ip-version` / `ha-connections` в `config.yml`):

```powershell
cloudflared tunnel run ghosteek-cr-api
```

Проверка:

```powershell
curl https://api.example.com/api/health
```

### Если `tunnel login` / `tunnel create` сыпят ошибками

Частые причины:

- не открылась авторизация в браузере — повторите `cloudflared tunnel login`;
- домен не добавлен в Cloudflare — сначала добавьте зону в [dash.cloudflare.com](https://dash.cloudflare.com);
- антивирус/фаервол блокирует `cloudflared` — разрешите исходящие **TCP 443**;
- для Quick Tunnel login **не нужен** — только для Named Tunnel.

---

## Связка Vercel + локальный бот

```
Mini App (Vercel)  →  Cloudflare Tunnel  →  127.0.0.1:8080  →  bot.main + SQLite
Telegram Bot (/link)  ────────────────────────────────↑  та же БД, тот же BOT_TOKEN
```

| Где | Переменная | Значение |
|-----|------------|----------|
| Vercel | `VITE_API_URL` | URL туннеля без `/` в конце |
| `.env` | `WEBAPP_URL` | URL Vercel |
| BotFather | Menu Button | URL Vercel |

После смены `VITE_API_URL` — **Redeploy** на Vercel.

В боте: `/link #ТЕГ`, при необходимости `/subscribe`. Mini App открывать **из Telegram**, не из браузера.

---

## Скрипт быстрого запуска (Windows)

```powershell
.\scripts\cloudflare-tunnel\start-quick.ps1
```

Запускает Quick Tunnel с рабочими флагами и выводит URL для копирования в Vercel.
