# localtunnel для Ghosteek CR Assistant

## Почему `npx localtunnel` постоянно завершается

| Причина | Что происходит |
|--------|----------------|
| **Терминал Cursor / фоновый агент** | При завершении сессии Cursor **убивает** дочерние `npx`/`node` → туннель мёртв через 1–3 мин |
| **Сервис loca.lt** | Проект **не поддерживается**; сервер сам рвёт idle-соединения (exit code 0) |
| **Закрыли окно PowerShell** | Процесс завершился → 503 на старом URL |
| **Сон / перезагрузка ПК** | Туннель обрывается |
| **Несколько копий** | Два `npx localtunnel --port 8080` → конфликты и путаница с URL |
| **Subdomain «busy» после перезагрузки ПК** | Имена на loca.lt **глобальные**; сервер держит «зомби»-резерв часами. Перезагрузка ПК не помогает. Используйте другое имя: `-Subdomain ghosteekcr2` |

**Вывод:** голый `npx localtunnel` в Cursor — не «постоянный» режим. Нужно отдельное окно + автоперезапуск (скрипт ниже).

Проверка:

```powershell
curl.exe -H "Bypass-Tunnel-Reminder: true" "https://ВАШ-URL.loca.lt/api/health"
```

---

## Как запускать (рекомендуется)

**Один процесс — бот + туннель:**

```powershell
cd G:\проги\ss
python -m bot.main
```

При старте бот:
1. поднимает API на `:8080`;
2. останавливает старые процессы localtunnel;
3. запускает `start-tunnel.ps1` с subdomain **`ghosteekcr`** → `https://ghosteekcr.loca.lt`.

Отдельное окно для туннеля **не нужно** (можно закрыть, если было открыто раньше).

Отключить автозапуск: в `.env` → `TUNNEL_AUTO_START=false`, тогда вручную:

```powershell
cd G:\проги\ss\scripts\localtunnel
.\start-tunnel.ps1
```

---

## Ручной режим (два окна)

**Окно 1 — бот** (`TUNNEL_AUTO_START=false`):

```powershell
cd G:\проги\ss
python -m bot.main
```

**Окно 2 — туннель:**

```powershell
cd G:\проги\ss\scripts\localtunnel
.\start-tunnel.ps1
```

С **фиксированным subdomain** (URL не меняется при перезапуске, если имя свободно):

```powershell
.\start-tunnel.ps1 -Subdomain ghosteekcr2
```

Если имя «busy» — loca.lt держит его на своих серверах (не на вашем ПК). Скрипт остановится после 3 попыток. Обновите **один раз** на Vercel: `VITE_API_URL=https://ghosteekcr2.loca.lt`

Случайный URL при каждом перезапуске: `.\start-tunnel.ps1 -AllowRandomFallback`

Скрипт:
- проверяет, что бот на `:8080` жив;
- перезапускает localtunnel при обрыве;
- пишет URL в `tunnel-url.txt`.

**Не закрывайте окно 2.**

Статус loca.lt: https://status.loca.lt
