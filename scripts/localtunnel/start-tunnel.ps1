# Стабильный запуск localtunnel к боту на :8080
# Запускайте в ОТДЕЛЬНОМ окне PowerShell (Win+R -> powershell), не закрывайте окно.

$Port = 8080
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

Write-Host "=== Ghosteek localtunnel ===" -ForegroundColor Cyan

if (-not (Test-Backend)) {
    Write-Host "Backend не отвечает на :$Port. Сначала: cd `"$Root`"; python -m bot.main" -ForegroundColor Red
    exit 1
}

Stop-ExistingTunnels

Write-Host "Backend OK. Туннель перезапускается автоматически при падении." -ForegroundColor Green
Write-Host "URL -> Vercel VITE_API_URL -> Redeploy`n" -ForegroundColor Yellow

$attempt = 0
while ($true) {
    $attempt++
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Запуск localtunnel (попытка $attempt)..." -ForegroundColor Cyan

    if (-not (Test-Backend)) {
        Write-Host "Backend offline — жду 10 сек..." -ForegroundColor Red
        Start-Sleep -Seconds 10
        continue
    }

    # npx блокирует окно, пока туннель жив; при выходе — цикл перезапустит
    $job = Start-Job -ScriptBlock {
        param($Root, $Port)
        Set-Location $Root
        npx --yes localtunnel --port $Port 2>&1
    } -ArgumentList $Root, $Port

    $url = $null
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $lines = Receive-Job $job -ErrorAction SilentlyContinue
        foreach ($line in $lines) {
            Write-Host $line
            if ($line -match "(https://[\w-]+\.loca\.lt)") {
                $url = $Matches[1]
            }
        }
        if ($url) {
            Set-Content -Path $using:UrlFile -Value $url -Encoding UTF8
            Write-Host "`n>>> URL: $url <<<`n" -ForegroundColor Green
            Write-Host "Скопируйте в Vercel -> Environment Variables -> VITE_API_URL -> Redeploy`n" -ForegroundColor Yellow
            break
        }
        if ($job.State -eq "Completed" -or $job.State -eq "Failed") { break }
        Start-Sleep -Milliseconds 400
    }

    Wait-Job $job | Out-Null
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Туннель упал. Перезапуск через 5 сек...`n" -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}
