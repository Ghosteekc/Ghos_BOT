# Cloudflare quick tunnel to bot on :8080 (replacement for broken loca.lt TLS).
# Usage:
#   .\start-tunnel.ps1
#   .\start-tunnel.ps1 -KillOnly
#   .\start-tunnel.ps1 -CloudflaredPath "C:\Program Files (x86)\cloudflared\cloudflared.exe"
#
# After start, copy the printed https://*.trycloudflare.com URL into webapp/vercel.json
# (rewrites destination) and redeploy — quick tunnel URLs change every restart.
# For a fixed hostname: cloudflared tunnel login + named tunnel (see README.md).

param(
    [int]$Port = 8080,
    [string]$CloudflaredPath = "",
    [switch]$KillOnly,
    [int]$HealthIntervalSec = 30,
    [int]$HealthFailLimit = 3,
    [int]$ConnectTimeoutSec = 60
)

$ErrorActionPreference = "Continue"
$LogFile = Join-Path $PSScriptRoot "tunnel.log"
$UrlFile = Join-Path $PSScriptRoot "tunnel-url.txt"
$ChildPidFile = Join-Path $PSScriptRoot "tunnel-child.pid"
$SupervisorPidFile = Join-Path $PSScriptRoot "tunnel-supervisor.pid"
$ExpectedLocal = "http://127.0.0.1:$Port/api/health"

function Write-LogLine {
    param([string]$Message, [string]$Color = "White")
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line -ForegroundColor $Color
}

function Resolve-Cloudflared {
    if ($CloudflaredPath -and (Test-Path $CloudflaredPath)) {
        return (Resolve-Path $CloudflaredPath).Path
    }
    $candidates = @(
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "$env:LOCALAPPDATA\cloudflared\cloudflared.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Test-Backend {
    try {
        $r = Invoke-WebRequest -Uri $ExpectedLocal -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Test-TunnelPublicHealth {
    param([string]$BaseUrl)
    if (-not $BaseUrl) { return $false }
    $url = ($BaseUrl.TrimEnd("/") + "/api/health")
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 12
        return ($r.StatusCode -eq 200 -and $r.Content -match '"status"\s*:\s*"ok"')
    } catch {
        return $false
    }
}

function Stop-ProcessTree {
    param([int]$ProcessId, [string]$Reason = "")
    if ($ProcessId -le 0) { return }
    if ($Reason) {
        Write-LogLine "Killing process tree PID $ProcessId ($Reason)" "Yellow"
    }
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

function Stop-AllCloudflaredQuick {
    Write-LogLine "Stopping previous cloudflared quick tunnels..." "Yellow"
    if (Test-Path $ChildPidFile) {
        $pidText = (Get-Content $ChildPidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        $oldPid = 0
        if ([int]::TryParse($pidText, [ref]$oldPid) -and $oldPid -gt 0) {
            Stop-ProcessTree -ProcessId $oldPid -Reason "tracked child"
        }
        Remove-Item $ChildPidFile -ErrorAction SilentlyContinue
    }

    Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "tunnel\s+--url\s+http://127\.0\.0\.1:$Port" -or $_.CommandLine -match "trycloudflare" -or $_.CommandLine -match "tunnel --url" } |
        ForEach-Object {
            Stop-ProcessTree -ProcessId $_.ProcessId -Reason "cloudflared --url"
        }

    if (Test-Path $SupervisorPidFile) {
        Remove-Item $SupervisorPidFile -ErrorAction SilentlyContinue
    }
}

function Save-TunnelUrl {
    param([string]$Url)
    Set-Content -Path $UrlFile -Value $Url -Encoding UTF8
    Write-LogLine "Saved URL to: $UrlFile" "DarkGray"
}

function Write-SuccessBanner {
    param([string]$Url)
    Write-LogLine "========================================" "Green"
    Write-LogLine "Tunnel OK: $Url" "Green"
    Write-LogLine "Public health: $Url/api/health" "Green"
    Write-LogLine "Update webapp/vercel.json rewrite to:" "Yellow"
    Write-LogLine "  $Url/api/:path*" "Yellow"
    Write-LogLine "then redeploy Vercel (quick URL changes on restart)." "Yellow"
    Write-LogLine "========================================" "Green"
}

if ($KillOnly) {
    Stop-AllCloudflaredQuick
    Write-LogLine "KillOnly done." "Green"
    exit 0
}

$cf = Resolve-Cloudflared
if (-not $cf) {
    Write-LogLine "cloudflared.exe not found. Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/" "Red"
    exit 2
}

Set-Content -Path $SupervisorPidFile -Value "$PID" -Encoding ASCII
Write-LogLine "=== Ghosteek Cloudflare Tunnel ===" "Cyan"
Write-LogLine "cloudflared: $cf" "DarkGray"
Write-LogLine "Log file: $LogFile" "DarkGray"
Write-LogLine "Supervisor PID: $PID" "DarkGray"

Stop-AllCloudflaredQuick

if (-not (Test-Backend)) {
    Write-LogLine "Waiting for backend on :$Port ..." "Yellow"
    $deadline = [datetime]::UtcNow.AddSeconds(45)
    while (-not (Test-Backend) -and [datetime]::UtcNow -lt $deadline) {
        Start-Sleep -Seconds 1
    }
}
if (Test-Backend) {
    Write-LogLine "Backend is online on port $Port" "Green"
} else {
    Write-LogLine "Backend not ready yet - tunnel will retry until API is up." "Yellow"
}

$session = 0
while ($true) {
    $session++
    if (-not (Test-Backend)) {
        Write-LogLine "Backend offline - waiting..." "Yellow"
        Start-Sleep -Seconds 5
        continue
    }

    Write-LogLine "Starting cloudflared session #$session..." "Cyan"
    $errLog = Join-Path $PSScriptRoot "cloudflared-session.err.log"
    $outLog = Join-Path $PSScriptRoot "cloudflared-session.out.log"
    Remove-Item $errLog, $outLog -ErrorAction SilentlyContinue

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $cf
    $psi.Arguments = "tunnel --url http://127.0.0.1:$Port --no-autoupdate"
    $psi.WorkingDirectory = $PSScriptRoot
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    Set-Content -Path $ChildPidFile -Value "$($proc.Id)" -Encoding ASCII
    Write-LogLine "Started cloudflared PID $($proc.Id)" "DarkGray"

    $tunnelUrl = $null
    $readyAnnounced = $false
    $healthFails = 0
    $nextHealthAt = [datetime]::UtcNow
    $connectDeadline = [datetime]::UtcNow.AddSeconds($ConnectTimeoutSec)
    $stderrBuf = New-Object System.Text.StringBuilder

    while (-not $proc.HasExited) {
        if (-not (Test-Backend)) {
            Write-LogLine "Backend offline - stopping tunnel until API is back..." "Yellow"
            Stop-ProcessTree -ProcessId $proc.Id -Reason "backend lost"
            break
        }

        while ($proc.StandardError.Peek() -ge 0) {
            $line = $proc.StandardError.ReadLine()
            if (-not $line) { continue }
            [void]$stderrBuf.AppendLine($line)
            Add-Content -Path $errLog -Value $line -Encoding UTF8
            if ($line -match "(https://[a-z0-9-]+\.trycloudflare\.com)") {
                $tunnelUrl = $Matches[1]
                Save-TunnelUrl -Url $tunnelUrl
                Write-LogLine "Got URL: $tunnelUrl" "Cyan"
            }
        }

        while ($proc.StandardOutput.Peek() -ge 0) {
            $line = $proc.StandardOutput.ReadLine()
            if ($line) {
                Add-Content -Path $outLog -Value $line -Encoding UTF8
                Write-LogLine $line "DarkGray"
            }
        }

        if (-not $tunnelUrl -and [datetime]::UtcNow -ge $connectDeadline) {
            Write-LogLine "No trycloudflare URL within ${ConnectTimeoutSec}s - restarting." "Red"
            Stop-ProcessTree -ProcessId $proc.Id -Reason "connect timeout"
            break
        }

        if ($tunnelUrl -and -not $readyAnnounced) {
            if (Test-TunnelPublicHealth -Url $tunnelUrl) {
                Write-SuccessBanner -Url $tunnelUrl
                $readyAnnounced = $true
                $healthFails = 0
                $nextHealthAt = [datetime]::UtcNow.AddSeconds($HealthIntervalSec)
            } elseif ([datetime]::UtcNow -ge $connectDeadline) {
                Write-LogLine "URL printed but public /api/health never OK - restarting." "Red"
                Stop-ProcessTree -ProcessId $proc.Id -Reason "public health timeout"
                break
            }
        }

        if ($readyAnnounced -and [datetime]::UtcNow -ge $nextHealthAt) {
            if (Test-TunnelPublicHealth -Url $tunnelUrl) {
                $healthFails = 0
            } else {
                $healthFails++
                Write-LogLine "Public health fail $healthFails/$HealthFailLimit ($tunnelUrl)" "Yellow"
                if ($healthFails -ge $HealthFailLimit) {
                    Write-LogLine "Public tunnel dead - restarting cloudflared." "Red"
                    Stop-ProcessTree -ProcessId $proc.Id -Reason "public health failed"
                    break
                }
            }
            $nextHealthAt = [datetime]::UtcNow.AddSeconds($HealthIntervalSec)
        }

        Start-Sleep -Milliseconds 400
    }

    if (-not $proc.HasExited) {
        try { $proc.WaitForExit(5000) | Out-Null } catch { }
    }
    Write-LogLine "cloudflared exited (code $($proc.ExitCode)). Restart in 5s..." "Yellow"
    Remove-Item $ChildPidFile -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
}
