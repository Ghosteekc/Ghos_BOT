# Стабильный localtunnel к боту на :8080
# Запускайте в ОТДЕЛЬНОМ окне Windows PowerShell — НЕ в терминале Cursor.
#
# Примеры:
#   .\start-tunnel.ps1
#   .\start-tunnel.ps1 -Subdomain ghosteekcr   # тот же URL после перезапуска (если имя свободно)

param(
    [int]$Port = 8080,
    [string]$Subdomain = ""
)

$Root = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
$UrlFile = Join-Path $PSScriptRoot "tunnel-url.txt"

function Test-Backend {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        return $r.status -eq "ok"
    } catch {
        return $false
    }
}

function Stop-ExistingTunnels {
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "localtunnel|lt\.js" } |
        ForEach-Object {
            Write-Host "Останавливаю старый localtunnel (PID $($_.ProcessId))" -ForegroundColor Yellow
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 1
}

function Save-TunnelUrl {
    param([string]$Url)
    if (-not $Url) { return }
    Set-Content -Path $UrlFile -Value $Url -Encoding UTF8
    Write-Host ""
    Write-Host ">>> URL: $Url <<<" -ForegroundColor Green
    Write-Host "Сохранено в: $UrlFile" -ForegroundColor DarkGray
    Write-Host "Vercel -> VITE_API_URL -> Redeploy (только если URL изменился)`n" -ForegroundColor Yellow
}

Write-Host "=== Ghosteek localtunnel ===" -ForegroundColor Cyan
Write-Host "Не закрывайте это окно. Cursor убивает фоновые npx при завершении сессии.`n" -ForegroundColor DarkGray

if (-not (Test-Backend)) {
    Write-Host "Backend не отвечает на :$Port. Сначала: cd `"$Root`"; python -m bot.main" -ForegroundColor Red
    exit 1
}

Stop-ExistingTunnels

$ltArgs = @("--yes", "localtunnel", "--port", "$Port")
if ($Subdomain) {
    $ltArgs += @("--subdomain", $Subdomain)
    Write-Host "Запрошен subdomain: $Subdomain (URL стабильнее между перезапусками)" -ForegroundColor Cyan
}

Write-Host "Backend OK. Автоперезапуск при обрыве loca.lt.`n" -ForegroundColor Green

$attempt = 0
while ($true) {
    $attempt++
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Запуск localtunnel (попытка $attempt)..." -ForegroundColor Cyan

    if (-not (Test-Backend)) {
        Write-Host "Backend offline — жду 10 сек..." -ForegroundColor Red
        Start-Sleep -Seconds 10
        continue
    }

    Set-Location $Root
    $savedUrl = $false

    # npx в foreground: пока процесс жив — туннель работает; при exit — цикл перезапустит
    & npx @ltArgs 2>&1 | ForEach-Object {
        $line = "$_"
        Write-Host $line
        if ($line -match "(https://[\w-]+\.loca\.lt)") {
            if (-not $savedUrl) {
                Save-TunnelUrl -Url $Matches[1]
                $savedUrl = $true
            }
        }
    }

    $exitCode = $LASTEXITCODE
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Туннель завершился (код $exitCode). Перезапуск через 5 сек...`n" -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}
