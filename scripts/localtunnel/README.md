# localtunnel для Ghosteek CR Assistant

## Почему `npx localtunnel` постоянно завершается

| Причина | Что происходит |
|--------|----------------|
| **Терминал Cursor / фоновый агент** | При завершении сессии Cursor **убивает** дочерние `npx`/`node` → туннель мёртв через 1–3 мин |
| **Сервис loca.lt** | Проект **не поддерживается**; сервер сам рвёт idle-соединения (exit code 0) |
| **Закрыли окно PowerShell** | Процесс завершился → 503 на старом URL |
| **Сон / перезагрузка ПК** | Туннель обрывается |
| **Несколько копий** | Два `npx localtunnel --port 8080` → конфликты и путаница с URL |
| **Сиротский `node lt.js`** | Если убить только окно PowerShell, дочерний `node` часто **остаётся** и держит `ghosteekcr` (loca.lt отдаёт чужой URL). Скрипт при старте делает **tree-kill** всех своих процессов |
| **Subdomain «busy» на стороне loca.lt** | Имя глобальное; после очистки локальных процессов сервер может ещё десятки секунд держать резерв — скрипт ретраит автоматически. Если долго не отпускает: `.\start-tunnel.ps1 -Subdomain ghosteekcr2` |
| **Зомби-туннель** | `node` жив, бот на `:8080` отвечает локально, а `https://ghosteekcr.loca.lt` снаружи мёртв (без ошибок в окне). Скрипт каждые 30 с бьёт `/api/health` снаружи и после 3 фейлов **сам перезапускает** туннель |
| **loca.lt homepage недоступен** | Проверка главной страницы часто падает (блок/флэйк), хотя туннель ещё можно поднять. Скрипт **не выходит**, а ретраит; жёсткий выход только с `-StrictLocaLtCheck` |

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

Только убить все старые туннели (без запуска):

```powershell
.\start-tunnel.ps1 -KillOnly
```

Скрипт:
- перед стартом убивает предыдущие `node lt.js` / supervisor’ы (**process tree**);
- держит один mutex — второй запуск перехватывает lock;
- проверяет, что бот на `:8080` жив;
- перезапускает localtunnel при обрыве и при «чужом» subdomain;
- пишет URL в `tunnel-url.txt`.

**Не закрывайте окно 2.**

Статус loca.lt: https://status.loca.lt
