# Stable localtunnel to bot on :8080 - only fixed subdomain ghosteekcr.
# Run in a SEPARATE Windows PowerShell window - NOT in Cursor terminal.
#
#   .\start-tunnel.ps1
#   .\start-tunnel.ps1 -Subdomain ghosteekcr

param(
    [int]$Port = 8080,
    [string]$Subdomain = "ghosteekcr",
    [switch]$SkipLocaLtCheck
)

$ErrorActionPreference = "Continue"
$Root = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
$UrlFile = Join-Path $PSScriptRoot "tunnel-url.txt"
$LogFile = Join-Path $PSScriptRoot "tunnel.log"
$ExpectedUrl = "https://$Subdomain.loca.lt"
$MyPid = $PID

function Write-LogLine {
    param([string]$Message, [string]$Color = "White")
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$stamp] $Message"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Write-SuccessBanner {
    param([string]$Url)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  TUNNEL READY" -ForegroundColor Green
    Write-Host "  $Url" -ForegroundColor Green
    Write-Host "  Backend port $Port - OK" -ForegroundColor Green
    Write-Host "  Public API health - OK" -ForegroundColor Green
    Write-Host "  Do not close this window." -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-LogLine "TUNNEL READY: $Url (public health OK)" "Green"
}

function Test-Backend {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        return $r.status -eq "ok"
    } catch {
        return $false
    }
}

function Wait-ForBackend {
    while (-not (Test-Backend)) {
        $hint = "Waiting for backend on port $Port - run: cd `"$Root`"; python -m bot.main"
        Write-LogLine $hint "Yellow"
        Start-Sleep -Seconds 5
    }
    Write-LogLine "Backend is online on port $Port" "Green"
}

function Test-TunnelPublicHealth {
    param([string]$Url)
    try {
        $headers = @{ "Bypass-Tunnel-Reminder" = "true" }
        $r = Invoke-RestMethod -Uri "$Url/api/health" -Headers $headers -TimeoutSec 20
        return $r.status -eq "ok"
    } catch {
        return $false
    }
}

function Test-LocaLt {
    try {
        $r = Invoke-WebRequest -Uri "https://loca.lt/" -TimeoutSec 8 -UseBasicParsing
        return $r.StatusCode -ge 200
    } catch {
        return $false
    }
}

function Stop-ExistingTunnels {
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "localtunnel|lt\.js" } |
        ForEach-Object {
            Write-LogLine "Stopping localtunnel node (PID $($_.ProcessId))" "Yellow"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "localtunnel|lt\.js" } |
        ForEach-Object {
            Write-LogLine "Stopping localtunnel cmd (PID $($_.ProcessId))" "Yellow"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessId -ne $MyPid -and
            $_.CommandLine -match "start-tunnel\.ps1"
        } |
        ForEach-Object {
            Write-LogLine "Stopping other tunnel supervisor (PID $($_.ProcessId))" "Yellow"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    Start-Sleep -Seconds 2
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

function Save-TunnelUrl {
    param([string]$Url)
    Set-Content -Path $UrlFile -Value $Url -Encoding UTF8
    Write-LogLine "Saved URL to: $UrlFile" "DarkGray"
}

function Test-SubdomainUrl {
    param([string]$Url)
    return $Url -match "https://$([regex]::Escape($Subdomain))\.loca\.lt/?$"
}

function Start-LocalTunnelSession {
    param([string]$LtJs)

    Write-LogLine "Command: node `"$LtJs`" --port $Port --subdomain $Subdomain" "DarkGray"
    Write-LogLine "Connecting to loca.lt (only $Subdomain allowed)..." "Yellow"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "node"
    $psi.Arguments = "`"$LtJs`" --port $Port --subdomain $Subdomain"
    $psi.WorkingDirectory = $PSScriptRoot
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()

    $savedUrl = $false
    $wrongSubdomain = $false
    $backendLost = $false
    $readyAnnounced = $false

    while (-not $proc.HasExited) {
        if (-not (Test-Backend)) {
            Write-LogLine "Backend offline - stopping tunnel until API is back..." "Yellow"
            $backendLost = $true
            break
        }

        while ($proc.StandardOutput.Peek() -ge 0) {
            $line = $proc.StandardOutput.ReadLine()
            if (-not $line) { continue }
            Write-LogLine $line

            if ($line -match "(https://[\w-]+\.loca\.lt)") {
                $url = $Matches[1]
                if (Test-SubdomainUrl -Url $url) {
                    $savedUrl = $true
                    Save-TunnelUrl -Url $url
                } elseif (-not $wrongSubdomain) {
                    $wrongSubdomain = $true
                    Write-LogLine "Subdomain $Subdomain is busy - loca.lt gave: $url" "Red"
                    Write-LogLine "Wrong tunnel killed. Retrying $ExpectedUrl only..." "Yellow"
                    break
                }
            }
        }

        while ($proc.StandardError.Peek() -ge 0) {
            $line = $proc.StandardError.ReadLine()
            if ($line) { Write-LogLine $line "DarkGray" }
        }

        if ($wrongSubdomain) {
            break
        }

        if ($savedUrl -and -not $readyAnnounced) {
            if (Test-TunnelPublicHealth -Url $ExpectedUrl) {
                Write-SuccessBanner -Url $ExpectedUrl
                $readyAnnounced = $true
            }
        }

        Start-Sleep -Milliseconds 400
    }

    if (-not $proc.HasExited) {
        try { $proc.Kill() } catch { }
        $proc.WaitForExit(3000) | Out-Null
    }

    return @{
        WrongSubdomain = $wrongSubdomain
        BackendLost = $backendLost
        ReadyAnnounced = $readyAnnounced
        ExitCode = $proc.ExitCode
    }
}

Write-LogLine "=== Ghosteek localtunnel ===" "Cyan"
Write-LogLine "Fixed subdomain: $Subdomain -> $ExpectedUrl" "Cyan"
Write-LogLine "Log file: $LogFile" "DarkGray"
Write-LogLine "Stopping all other localtunnel processes..." "Yellow"

Stop-ExistingTunnels

if (-not $SkipLocaLtCheck) {
    Write-LogLine "Checking loca.lt reachability..." "Cyan"
    if (-not (Test-LocaLt)) {
        Write-LogLine "loca.lt is NOT reachable from this network." "Red"
        Write-LogLine "Try VPN or mobile hotspot, then run this script again." "Yellow"
        Write-LogLine "Or force start: .\start-tunnel.ps1 -SkipLocaLtCheck" "DarkGray"
        exit 4
    }
    Write-LogLine "loca.lt OK." "Green"
}

$LtJs = Ensure-LocalLt
Wait-ForBackend

Write-LogLine "Supervisor started. Retries until $ExpectedUrl is active or you close this window." "Cyan"

$session = 0
$reclaimAttempt = 0

while ($true) {
    Wait-ForBackend

    if (-not (Test-Backend)) {
        continue
    }

    Stop-ExistingTunnels
    $session++
    Write-LogLine "Starting localtunnel session #$session..." "Cyan"

    $result = Start-LocalTunnelSession -LtJs $LtJs

    if ($result.BackendLost) {
        Write-LogLine "Waiting for backend to return..." "Yellow"
        Stop-ExistingTunnels
        continue
    }

    if ($result.WrongSubdomain) {
        $reclaimAttempt++
        $waitSec = [Math]::Min(10 + ($reclaimAttempt * 5), 60)
        Write-LogLine "Reclaim attempt $reclaimAttempt - waiting ${waitSec}s before retry..." "Yellow"
        Stop-ExistingTunnels
        Start-Sleep -Seconds $waitSec
        continue
    }

    $reclaimAttempt = 0
    $exitCode = $result.ExitCode

    if ($result.ReadyAnnounced) {
        Write-LogLine "Tunnel session ended (code $exitCode). Restarting in 5 sec..." "Yellow"
    } else {
        Write-LogLine "Tunnel exited before ready (code $exitCode). Restart in 5 sec..." "Yellow"
    }

    Stop-ExistingTunnels
    Start-Sleep -Seconds 5
}
