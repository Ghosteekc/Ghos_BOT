# Tunnel to bot on :8080 (loca.lt or Cloudflare auto-fallback)
# Run in a SEPARATE Windows PowerShell window - NOT in Cursor terminal.
#
# Examples:
#   .\start-tunnel.ps1
#   .\start-tunnel.ps1 -Subdomain ghosteekcr

param(
    [int]$Port = 8080,
    [string]$Subdomain = "",
    [int]$MaxReclaimAttempts = 3,
    [switch]$AllowRandomFallback,
    [switch]$ForceCloudflare,
    [switch]$ForceLocaltunnel
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
    Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Write-LogLine "Stopping cloudflared (PID $($_.ProcessId))" "Yellow"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 2
}

function Resolve-Cloudflared {
    $candidates = @(
        "C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "C:\Program Files\cloudflared\cloudflared.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    Write-LogLine "cloudflared not found. Install: winget install Cloudflare.cloudflared" "Red"
    exit 5
}

function Test-LocaLt {
    try {
        $r = Invoke-WebRequest -Uri "https://loca.lt/" -TimeoutSec 8 -UseBasicParsing
        return $r.StatusCode -ge 200
    } catch {
        return $false
    }
}

function Ensure-LocalLt {
    $ltJs = Join-Path $PSScriptRoot "node_modules\localtunnel\bin\lt.js"
    if (Test-Path $ltJs) {
        return $ltJs
    }

    Write-LogLine "First run: npm install in scripts/localtunnel (one time)..." "Yellow"
    Set-Location $PSScriptRoot
    & npm install 2>&1 | ForEach-Object { Write-LogLine $_ "DarkGray" }
    if (-not (Test-Path $ltJs)) {
        Write-LogLine "npm install failed. Run manually: cd `"$PSScriptRoot`"; npm install" "Red"
        exit 3
    }
    return $ltJs
}

function Build-LtRunArgs {
    $runArgs = @("--port", "$Port")
    if ($Subdomain) {
        $runArgs += @("--subdomain", $Subdomain)
    }
    return $runArgs
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
    if ($Url -match "trycloudflare\.com") {
        Write-LogLine "Vercel -> VITE_API_URL -> $Url -> Redeploy (once per new Cloudflare URL)" "Yellow"
    } elseif ($Force -and $Subdomain) {
        Write-LogLine "Using random URL because subdomain is stuck on loca.lt servers." "Yellow"
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
        Write-LogLine ("Subdomain {0} busy - loca.lt gave: {1}" -f $Subdomain, $url) "Red"
        Write-LogLine "Wait and restart, or use: -AllowRandomFallback" "Yellow"
        return $true
    }

    if (Save-TunnelUrl -Url $url) {
        $SavedUrl.Value = $true
    }
    return $false
}

function Start-LocalTunnelSession {
    param(
        [string]$LtJs,
        [switch]$AcceptRandom
    )

    $savedUrl = [ref]$false
    $wrongSubdomain = [ref]$false
    $runArgs = Build-LtRunArgs

    Write-LogLine ("Command: node lt.js {0}" -f ($runArgs -join " ")) "DarkGray"
    Write-LogLine "Connecting to loca.lt server (10-30 sec)..." "Yellow"

    Set-Location $PSScriptRoot
    & node $LtJs @runArgs 2>&1 | ForEach-Object {
        if (Process-LtOutputLine -Line "$_" -SavedUrl $savedUrl -AcceptRandom:$AcceptRandom) {
            $wrongSubdomain.Value = $true
        }
    }

    return @{
        ExitCode = $LASTEXITCODE
        WrongSubdomain = $wrongSubdomain.Value
        SavedUrl = $savedUrl.Value
    }
}

function Start-CloudflareTunnelSession {
    param([string]$CloudflaredPath)

    $savedUrl = [ref]$false
    Write-LogLine "Command: cloudflared tunnel --url http://127.0.0.1:$Port" "DarkGray"
    Write-LogLine "Starting Cloudflare Quick Tunnel..." "Yellow"

    & $CloudflaredPath tunnel `
        --url "http://127.0.0.1:$Port" `
        --protocol http2 `
        --edge-ip-version 4 `
        --ha-connections 1 2>&1 | ForEach-Object {
            $line = "$_"
            Write-LogLine $line
            if ($savedUrl.Value) { return }
            if ($line -match "(https://[\w-]+\.trycloudflare\.com)") {
                if (Save-TunnelUrl -Url $Matches[1] -Force) {
                    $savedUrl.Value = $true
                }
            }
        }

    return @{
        ExitCode = $LASTEXITCODE
        SavedUrl = $savedUrl.Value
    }
}

Write-LogLine "=== Ghosteek API tunnel ===" "Cyan"
Write-LogLine "Do not close this window. Cursor kills background npx when session ends." "DarkGray"
Write-LogLine "Log file: $LogFile" "DarkGray"

if (-not (Test-Backend)) {
    Write-LogLine "Backend not responding on :$Port. Start: cd `"$Root`"; python -m bot.main" "Red"
    exit 1
}

Stop-ExistingTunnels

$UseCloudflare = $ForceCloudflare.IsPresent
if (-not $UseCloudflare -and -not $ForceLocaltunnel.IsPresent) {
    Write-LogLine "Checking loca.lt reachability..." "Cyan"
    if (Test-LocaLt) {
        Write-LogLine "loca.lt OK - using localtunnel (classic mode)." "Green"
    } else {
        Write-LogLine "loca.lt is blocked on this network (ISP/router). It worked before when loca.lt was open." "Yellow"
        Write-LogLine "Auto-switching to Cloudflare tunnel - same script, same two windows." "Cyan"
        $UseCloudflare = $true
    }
} elseif ($ForceLocaltunnel.IsPresent) {
    Write-LogLine "ForceLocaltunnel: trying loca.lt even if blocked." "Yellow"
}

if ($UseCloudflare) {
    $CloudflaredPath = Resolve-Cloudflared
    Write-LogLine "Backend OK. Keep this window open." "Green"
    $attempt = 0
    while ($true) {
        if (-not (Test-Backend)) {
            Write-LogLine "Backend offline, waiting 10 sec..." "Red"
            Start-Sleep -Seconds 10
            continue
        }
        $attempt++
        Write-LogLine "Starting Cloudflare tunnel (session $attempt)..." "Cyan"
        $session = Start-CloudflareTunnelSession -CloudflaredPath $CloudflaredPath
        Write-LogLine "Tunnel exited (code $($session.ExitCode)). Restart in 10 sec..." "Yellow"
        Stop-ExistingTunnels
        Start-Sleep -Seconds 10
    }
}

$LtJs = Ensure-LocalLt

if ($Subdomain) {
    Write-LogLine "Requested subdomain: $Subdomain" "Cyan"
    Write-LogLine ("Vercel VITE_API_URL=https://{0}.loca.lt (no redeploy on tunnel restart)" -f $Subdomain) "Cyan"
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

    Set-Location $PSScriptRoot
    $session = Start-LocalTunnelSession -LtJs $LtJs -AcceptRandom:$AllowRandomFallback

    if ($session.WrongSubdomain) {
        $reclaimAttempt++
        if ($reclaimAttempt -ge $MaxReclaimAttempts) {
            Write-LogLine ("Subdomain {0} still busy after {1} attempt(s)." -f $Subdomain, $reclaimAttempt) "Red"
            Write-LogLine "loca.lt keeps names globally; rebooting PC does not release them." "Yellow"
            Write-LogLine "Try another name, e.g.: .\start-tunnel.ps1 -Subdomain ghosteekcr2" "Cyan"
            Write-LogLine "Or accept random URL: .\start-tunnel.ps1 -AllowRandomFallback" "Cyan"
            if ($AllowRandomFallback) {
                Write-LogLine "Starting without fixed subdomain..." "Yellow"
                $Subdomain = ""
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
