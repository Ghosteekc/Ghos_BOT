# VPS proxy для Clash Royale API

Схема:

```
Бот (ПК / VPS)  →  VPS nginx (статический IP)  →  api.clashroyale.com
                         ↑
               whitelist этого IP в developer.clashroyale.com
```

## Шаг 1. VPS со статическим IP (бесплатные варианты)

- **Oracle Cloud Always Free** — 1–2 VM с публичным IPv4 (нужна карта, но бесплатный tier).
- **Другие**: любой VPS от ~€4/мес (Hetzner, Timeweb) — проще, если Oracle не подходит.

После создания VM запишите **публичный IPv4**, например `203.0.113.50`.

## Шаг 2. Clash Royale API key

1. [developer.clashroyale.com](https://developer.clashroyale.com) → Create / Edit Key.
2. В **Allowed IP Addresses** добавьте **только IP VPS** (не IP вашего ПК).
3. Скопируйте **Token** — он пойдёт в `CLASH_ROYALE_API_KEY` в `.env` бота.

## Шаг 3. Nginx на VPS

Подключитесь по SSH:

```bash
sudo apt update && sudo apt install -y nginx
```

Скопируйте `scripts/cr-proxy/cr-proxy.conf` на сервер и отредактируйте секрет:

```bash
# На VPS — замените CHANGE_ME на длинную случайную строку (openssl rand -hex 32)
sudo nano /etc/nginx/sites-available/cr-proxy
```

```bash
sudo ln -sf /etc/nginx/sites-available/cr-proxy /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw enable
```

### Проверка прокси с VPS

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer ВАШ_CR_TOKEN" \
  -H "X-CR-Proxy-Secret: ВАШ_СЕКРЕТ" \
  "http://127.0.0.1/v1/players/%2320Q220Y9UY"
```

Ожидается `200`. Без секрета — `403`.

## Шаг 4. Переменные в `.env` бота

| Переменная | Значение |
|------------|----------|
| `CLASH_ROYALE_API_KEY` | Token с developer.clashroyale.com |
| `CLASH_ROYALE_API_BASE` | `http://IP_ВАШЕГО_VPS/v1` |
| `CLASH_ROYALE_PROXY_SECRET` | Тот же секрет, что в nginx |

Пример:

```
CLASH_ROYALE_API_BASE=http://203.0.113.50/v1
CLASH_ROYALE_PROXY_SECRET=a1b2c3d4e5f6...64 символа...
```

Перезапустите бота после изменения `.env`.

## Шаг 5. Проверка /link

В Telegram: `/link #ВАШТЕГ`

Если ошибка `invalidIp` — IP в whitelist не совпадает с IP VPS (проверьте `curl ifconfig.me` на VPS).

Если `Invalid authorization` — неверный `CLASH_ROYALE_API_KEY` в `.env`.

## HTTPS (опционально)

Для production лучше домен + Let's Encrypt:

1. Бесплатный домен (DuckDNS, etc.) → A-запись на IP VPS.
2. `sudo apt install certbot python3-certbot-nginx`
3. `sudo certbot --nginx -d your.domain.com`
4. В `.env`: `CLASH_ROYALE_API_BASE=https://your.domain.com/v1`

## Безопасность

- Секрет `X-CR-Proxy-Secret` не даёт посторонним использовать ваш прокси.
- API key храните только в `.env`, не в git.
- SSH на VPS — только по ключу, отключите password login.
