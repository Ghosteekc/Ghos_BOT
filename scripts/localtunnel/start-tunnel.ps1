# Stable localtunnel to bot on :8080
# Run in a SEPARATE Windows PowerShell window - NOT in Cursor terminal.
#
# Examples:
#   .\start-tunnel.ps1
#   .\start-tunnel.ps1 -Subdomain ghosteekcr

param(
    [int]$Port = 8080,
    [string]$Subdomain = "",
    [int]$MaxReclaimAttempts = 3,
    [switch]$AllowRandomFallback
)

$Root = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
$UrlFile = Join-Path $PSScriptRoot "tunnel-url.txt"
$LogFile = Join-Path $PSScriptRoot "tunnel.log"

function Test-Backend {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        return $r.status -eq "ok"
    } catch {
        return $false
    }
}

function Write-LogLine {
    param([string]$Message, [string]$Color = "White")
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$stamp] $Message"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Stop-ExistingTunnels {
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "localtunnel|lt\.js" } |
        ForEach-Object {
            Write-LogLine "Stopping localtunnel node (PID $($_.ProcessId))" "Yellow"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "localtunnel" } |
        ForEach-Object {
            Write-LogLine "Stopping localtunnel cmd (PID $($_.ProcessId))" "Yellow"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 2
}

function Test-SubdomainUrl {
    param([string]$Url)
    if (-not $Subdomain) { return $true }
    return $Url -match "https://$([regex]::Escape($Subdomain))\.loca\.lt/?$"
}

function Save-TunnelUrl {
    param(
        [string]$Url,
        [switch]$Force
    )
    if (-not $Url) { return $false }
    if (-not $Force -and -not (Test-SubdomainUrl -Url $Url)) {
        return $false
    }
    Set-Content -Path $UrlFile -Value $Url -Encoding UTF8
    Write-LogLine "Tunnel URL: $Url" "Green"
    Write-LogLine "Saved to: $UrlFile" "DarkGray"
    if ($Force -and $Subdomain) {
        Write-LogLine "Using random URL because '$Subdomain' is stuck on loca.lt servers." "Yellow"
        Write-LogLine "Update Vercel VITE_API_URL to: $Url" "Yellow"
    }
    return $true
}

function Process-LtOutputLine {
    param(
        [string]$Line,
        [ref]$SavedUrl,
        [switch]$AcceptRandom
    )

    if (-not $Line) { return $false }

    Write-LogLine $Line

    if ($Line -notmatch "(https://[\w-]+\.loca\.lt)") {
        return $false
    }

    $url = $Matches[1]
    if ($SavedUrl.Value) { return $false }

    if (Test-SubdomainUrl -Url $url) {
        if (Save-TunnelUrl -Url $url) {
            $SavedUrl.Value = $true
        }
        return $false
    }

    if ($AcceptRandom) {
        if (Save-TunnelUrl -Url $url -Force) {
            $SavedUrl.Value = $true
        }
        return $false
    }

    if ($Subdomain) {
        Write-LogLine "Subdomain '$Subdomain' busy — loca.lt выдал: $url" "Red"
        Write-LogLine "Подождите и перезапустите скрипт, или: -AllowRandomFallback" "Yellow"
        return $true
    }

    if (Save-TunnelUrl -Url $url) {
        $SavedUrl.Value = $true
    }
    return $false
}

function Start-LocalTunnelSession {
    param(
        [string[]]$Arguments,
        [switch]$AcceptRandom
    )

    $savedUrl = [ref]$false
    $wrongSubdomain = [ref]$false

    $ltCmd = Get-Command lt -ErrorAction SilentlyContinue
    if ($ltCmd) {
        Write-LogLine "Using lt: $($ltCmd.Source)" "DarkGray"
        $runArgs = @("--port", "$Port")
        if ($Subdomain) { $runArgs += @("--subdomain", $Subdomain) }
        Write-LogLine "Command: lt $($runArgs -join ' ')" "DarkGray"
    } else {
        Write-LogLine "Command: npx $($Arguments -join ' ')" "DarkGray"
        Write-LogLine "Если тишина 1-3 мин — npx скачивает localtunnel, это нормально." "Yellow"
    }

    Set-Location $Root

    if ($ltCmd) {
        & lt @runArgs 2>&1 | ForEach-Object {
            if (Process-LtOutputLine -Line "$_" -SavedUrl $savedUrl -AcceptRandom:$AcceptRandom) {
                $wrongSubdomain.Value = $true
            }
        }
    } else {
        & npx @Arguments 2>&1 | ForEach-Object {
            if (Process-LtOutputLine -Line "$_" -SavedUrl $savedUrl -AcceptRandom:$AcceptRandom) {
                $wrongSubdomain.Value = $true
            }
        }
    }

    return @{
        ExitCode = $LASTEXITCODE
        WrongSubdomain = $wrongSubdomain.Value
        SavedUrl = $savedUrl.Value
    }
}

Write-LogLine "=== Ghosteek localtunnel ===" "Cyan"
Write-LogLine "Do not close this window. Cursor kills background npx when session ends." "DarkGray"
Write-LogLine "Log file: $LogFile" "DarkGray"

if (-not (Test-Backend)) {
    Write-LogLine "Backend not responding on :$Port. Start: cd `"$Root`"; python -m bot.main" "Red"
    exit 1
}

Stop-ExistingTunnels

$ltArgs = @("--yes", "localtunnel", "--port", "$Port")
if ($Subdomain) {
    $ltArgs += @("--subdomain", $Subdomain)
    Write-LogLine "Requested subdomain: $Subdomain" "Cyan"
    Write-LogLine "Vercel: VITE_API_URL=https://$Subdomain.loca.lt (как у вас — redeploy не нужен при перезапуске)" "Cyan"
}

Write-LogLine "Backend OK. Auto-restart on loca.lt disconnect." "Green"

$attempt = 0
$reclaimAttempt = 0

while ($true) {
    if (-not (Test-Backend)) {
        Write-LogLine "Backend offline, waiting 10 sec..." "Red"
        Start-Sleep -Seconds 10
        continue
    }

    $attempt++
    Write-LogLine "Starting localtunnel (session $attempt)..." "Cyan"

    Set-Location $Root
    $session = Start-LocalTunnelSession -Arguments $ltArgs -AcceptRandom:$AllowRandomFallback

    if ($session.WrongSubdomain) {
        $reclaimAttempt++
        if ($reclaimAttempt -ge $MaxReclaimAttempts) {
            Write-LogLine "Subdomain '$Subdomain' still busy after $reclaimAttempt attempt(s)." "Red"
            Write-LogLine "loca.lt keeps names globally; rebooting PC does not release them." "Yellow"
            Write-LogLine "Try another name, e.g.: .\start-tunnel.ps1 -Subdomain ghosteekcr2" "Cyan"
            Write-LogLine "Or accept random URL: .\start-tunnel.ps1 -AllowRandomFallback" "Cyan"
            if ($AllowRandomFallback) {
                Write-LogLine "Starting without fixed subdomain..." "Yellow"
                $Subdomain = ""
                $ltArgs = @("--yes", "localtunnel", "--port", "$Port")
                $reclaimAttempt = 0
                continue
            }
            exit 2
        }
        $waitSec = [Math]::Min(15 + ($reclaimAttempt * 10), 45)
        Write-LogLine "Reclaim attempt $reclaimAttempt/$MaxReclaimAttempts failed. Waiting $waitSec sec..." "Yellow"
        Stop-ExistingTunnels
        Start-Sleep -Seconds $waitSec
        continue
    }

    $reclaimAttempt = 0
    $restartDelay = if ($Subdomain) { 10 } else { 5 }
    Write-LogLine "Tunnel exited (code $($session.ExitCode)). Restart in $restartDelay sec..." "Yellow"
    Stop-ExistingTunnels
    Start-Sleep -Seconds $restartDelay
}
