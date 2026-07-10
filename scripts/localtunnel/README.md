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

**Вывод:** голый `npx localtunnel` в Cursor — не «постоянный» режим. Нужно отдельное окно + автоперезапуск (скрипт ниже) или Cloudflare Tunnel.

Проверка:

```powershell
curl.exe -H "Bypass-Tunnel-Reminder: true" "https://ВАШ-URL.loca.lt/api/health"
```

---

## Как запускать (рекомендуется)

**Окно 1 — бот:**

```powershell
cd G:\проги\ss
python -m bot.main
```

**Окно 2 — туннель (Win+R → powershell, или двойной клик `start-tunnel.cmd`):**

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

---

## Более стабильная альтернатива

Cloudflare Tunnel реже падает, чем loca.lt:

```powershell
.\scripts\cloudflare-tunnel\start-quick.ps1
```

Named Tunnel — **постоянный** URL на своём домене (см. `scripts/cloudflare-tunnel/README.md`).

Статус loca.lt: https://status.loca.lt
