# Quick Tunnel с флагами, которые работают на вашей сети.
# URL меняется при каждом запуске — для постоянного адреса см. README.md (Named Tunnel).

$ErrorActionPreference = "Stop"

Write-Host "Проверка локального API..." -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/health" -TimeoutSec 3
    Write-Host "OK: $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Host "Backend не отвечает на :8080. Сначала запустите: python -m bot.main" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Запуск Cloudflare Quick Tunnel..." -ForegroundColor Cyan
Write-Host "Скопируйте https://....trycloudflare.com из вывода -> VITE_API_URL на Vercel -> Redeploy" -ForegroundColor Yellow
Write-Host ""

& cloudflared tunnel `
    --url http://127.0.0.1:8080 `
    --protocol http2 `
    --edge-ip-version 4 `
    --ha-connections 1
