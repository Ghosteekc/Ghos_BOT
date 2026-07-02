# localtunnel для Ghosteek CR Assistant

## Почему туннель «постоянно умирает»

Это **не проблема бота**. Типичные причины:

| Причина | Что происходит |
|--------|----------------|
| **Закрыли окно PowerShell** | Процесс `npx localtunnel` завершился → URL мёртв (503) |
| **Терминал Cursor** | «connection to shell process was lost» **убивает** фоновые процессы |
| **Сон / перезагрузка ПК** | Туннель обрывается |
| **Несколько копий localtunnel** | Два `npx localtunnel --port 8080` → путаница с URL |
| **Сервис loca.lt** | Проект **не поддерживается**, бывают массовые 503 |
| **Смена URL** | Каждый перезапуск = **новый** `*.loca.lt` → на Vercel старый `VITE_API_URL` |

Проверка:

```powershell
Invoke-WebRequest "https://ВАШ-URL.loca.lt/api/health" -Headers @{"Bypass-Tunnel-Reminder"="true"}
```

---

## Как запускать

**Окно 1 — бот:**

```powershell
cd G:\проги\ss
python -m bot.main
```

**Окно 2 — туннель (отдельное окно Windows, не Cursor):**

```powershell
cd G:\проги\ss\scripts\localtunnel
.\start-tunnel.ps1
```

---

## Альтернативы

- `scripts/cloudflare-tunnel/start-quick.ps1`
- Named Tunnel — постоянный URL
- Статус: https://status.loca.lt
