# Stable localtunnel to bot on :8080 - only fixed subdomain ghosteekcr.
# Run in a SEPARATE Windows PowerShell window - NOT in Cursor terminal.
#
#   .\start-tunnel.ps1
#   .\start-tunnel.ps1 -Subdomain ghosteekcr
#   .\start-tunnel.ps1 -KillOnly

param(
    [int]$Port = 8080,
    [string]$Subdomain = "ghosteekcr",
    [switch]$SkipLocaLtCheck,
    [switch]$KillOnly
)

$ErrorActionPreference = "Continue"
$Root = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
$UrlFile = Join-Path $PSScriptRoot "tunnel-url.txt"
$LogFile = Join-Path $PSScriptRoot "tunnel.log"
$SupervisorPidFile = Join-Path $PSScriptRoot "tunnel-supervisor.pid"
$ChildPidFile = Join-Path $PSScriptRoot "tunnel-child.pid"
$ExpectedUrl = "https://$Subdomain.loca.lt"
$MyPid = $PID
$MutexName = "Global\GhosteekLocalTunnelSupervisor"
$script:TunnelMutex = $null
$script:ChildProc = $null

function Write-LogLine {
    param([string]$Message, [string]$Color = "White")
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$stamp] $Message"
    Write-Host $line -ForegroundColor $Color
    try {
        Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch { }
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

function Stop-ProcessTree {
    param([int]$ProcessId, [string]$Reason = "")
    if ($ProcessId -le 0 -or $ProcessId -eq $MyPid) { return }
    try {
        $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if (-not $proc) { return }
    } catch { return }

    $suffix = if ($Reason) { " ($Reason)" } else { "" }
    Write-LogLine "Killing process tree PID $ProcessId$suffix" "Yellow"
    # /T = kill child tree (prevents orphaned node lt.js)
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    try { Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue } catch { }
}

function Get-TunnelRelatedProcesses {
    $patterns = @(
        "localtunnel",
        "lt\.js",
        "start-tunnel\.ps1",
        "start-tunnel\.cmd"
    )
    $pattern = ($patterns -join "|")

    $names = @("node.exe", "cmd.exe", "powershell.exe", "pwsh.exe")
    $found = @()
    foreach ($name in $names) {
        $procs = Get-CimInstance Win32_Process -Filter "Name='$name'" -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            if (-not $p.CommandLine) { continue }
            if ($p.ProcessId -eq $MyPid) { continue }
            if ($p.CommandLine -match $pattern) {
                $found += $p
            }
        }
    }
    return $found
}

function Stop-PidFileProcess {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path $Path)) { return }
    try {
        $raw = (Get-Content -Path $Path -Raw -ErrorAction SilentlyContinue).Trim()
        $pidVal = 0
        if ([int]::TryParse($raw, [ref]$pidVal) -and $pidVal -gt 0) {
            if ($pidVal -eq $MyPid) {
                # Our own supervisor pid file - keep it
                return
            }
            Stop-ProcessTree -ProcessId $pidVal -Reason $Label
        }
    } catch { }
    Remove-Item -Path $Path -Force -ErrorAction SilentlyContinue
}

function Stop-ExistingTunnels {
    param([switch]$Quiet)

    if (-not $Quiet) {
        Write-LogLine "Stopping all previous localtunnel processes (tree kill)..." "Yellow"
    }

    # 1) Kill tracked PIDs first (supervisor/child from previous runs)
    Stop-PidFileProcess -Path $ChildPidFile -Label "tracked child"
    Stop-PidFileProcess -Path $SupervisorPidFile -Label "tracked supervisor"

    # 2) Kill current child if we own one
    if ($script:ChildProc -and -not $script:ChildProc.HasExited) {
        try {
            Stop-ProcessTree -ProcessId $script:ChildProc.Id -Reason "session child"
        } catch { }
        $script:ChildProc = $null
    }

    # 3) Scan and tree-kill everything related (nodes first via sort: node before powershell)
    $related = @(Get-TunnelRelatedProcesses | Sort-Object {
        if ($_.Name -eq "node.exe") { 0 }
        elseif ($_.Name -match "cmd") { 1 }
        else { 2 }
    }, ProcessId)

    foreach ($p in $related) {
        Stop-ProcessTree -ProcessId $p.ProcessId -Reason $p.Name
    }

    # 4) Verify loop - orphans must not survive
    for ($i = 0; $i -lt 8; $i++) {
        Start-Sleep -Milliseconds 400
        $left = @(Get-TunnelRelatedProcesses)
        if ($left.Count -eq 0) { break }
        foreach ($p in $left) {
            Stop-ProcessTree -ProcessId $p.ProcessId -Reason "retry cleanup"
        }
    }

    $left = @(Get-TunnelRelatedProcesses)
    if ($left.Count -gt 0) {
        $ids = ($left | ForEach-Object { $_.ProcessId }) -join ", "
        Write-LogLine "WARNING: still alive after cleanup: $ids - forcing taskkill" "Red"
        foreach ($p in $left) {
            & taskkill.exe /PID $p.ProcessId /T /F 2>$null | Out-Null
        }
        Start-Sleep -Seconds 1
    } else {
        if (-not $Quiet) {
            Write-LogLine "No leftover localtunnel processes." "Green"
        }
    }

    # Give loca.lt time to drop the old TCP reservation
    Start-Sleep -Seconds 2
}

function Enter-TunnelMutex {
    $created = $false
    try {
        $script:TunnelMutex = New-Object System.Threading.Mutex($false, $MutexName)
        # Wait briefly; if another instance holds it, kill others and take over
        $got = $script:TunnelMutex.WaitOne(0)
        if (-not $got) {
            Write-LogLine "Another tunnel supervisor holds the lock - reclaiming..." "Yellow"
            Stop-ExistingTunnels
            $got = $script:TunnelMutex.WaitOne(5000)
            if (-not $got) {
                Write-LogLine "Could not acquire tunnel lock after cleanup. Forcing takeover..." "Red"
                try { $script:TunnelMutex.ReleaseMutex() } catch { }
                try { $script:TunnelMutex.Dispose() } catch { }
                $script:TunnelMutex = New-Object System.Threading.Mutex($true, $MutexName, [ref]$created)
            }
        }
        Set-Content -Path $SupervisorPidFile -Value "$MyPid" -Encoding ASCII
        return $true
    } catch {
        Write-LogLine "Mutex warning: $($_.Exception.Message) - continuing anyway" "Yellow"
        Set-Content -Path $SupervisorPidFile -Value "$MyPid" -Encoding ASCII
        return $true
    }
}

function Exit-TunnelMutex {
    try {
        if ($script:TunnelMutex) {
            try { $script:TunnelMutex.ReleaseMutex() } catch { }
            try { $script:TunnelMutex.Dispose() } catch { }
            $script:TunnelMutex = $null
        }
    } catch { }
    Remove-Item -Path $SupervisorPidFile -Force -ErrorAction SilentlyContinue
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
    $script:ChildProc = $proc
    Set-Content -Path $ChildPidFile -Value "$($proc.Id)" -Encoding ASCII
    Write-LogLine "Started lt child PID $($proc.Id)" "DarkGray"

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

    # Always tree-kill our child so it cannot become an orphan holding the subdomain
    if (-not $proc.HasExited) {
        Stop-ProcessTree -ProcessId $proc.Id -Reason "end of session"
        try { $proc.WaitForExit(5000) | Out-Null } catch { }
    } else {
        # Process exited on its own - still sweep orphans matching lt.js
        $orphans = @(Get-TunnelRelatedProcesses | Where-Object { $_.Name -eq "node.exe" })
        foreach ($o in $orphans) {
            Stop-ProcessTree -ProcessId $o.ProcessId -Reason "orphan after exit"
        }
    }

    $script:ChildProc = $null
    Remove-Item -Path $ChildPidFile -Force -ErrorAction SilentlyContinue

    return @{
        WrongSubdomain = $wrongSubdomain
        BackendLost = $backendLost
        ReadyAnnounced = $readyAnnounced
        ExitCode = if ($null -ne $proc.ExitCode) { $proc.ExitCode } else { -1 }
    }
}

# --- Main ---

try {
    Write-LogLine "=== Ghosteek localtunnel ===" "Cyan"
    Write-LogLine "Fixed subdomain: $Subdomain -> $ExpectedUrl" "Cyan"
    Write-LogLine "Log file: $LogFile" "DarkGray"
    Write-LogLine "Supervisor PID: $MyPid" "DarkGray"

    Stop-ExistingTunnels

    if ($KillOnly) {
        Write-LogLine "KillOnly: done." "Green"
        exit 0
    }

    if (-not (Enter-TunnelMutex)) {
        Write-LogLine "Failed to become the sole tunnel supervisor." "Red"
        exit 5
    }

    # Second sweep after taking the lock (previous instance may have spawned a child mid-kill)
    Stop-ExistingTunnels -Quiet

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

        # Fresh cleanup before every connect - never leave a previous lt holding the name
        Stop-ExistingTunnels -Quiet
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
            $waitSec = [Math]::Min(8 + ($reclaimAttempt * 4), 45)
            Write-LogLine "Reclaim attempt $reclaimAttempt - full cleanup, then wait ${waitSec}s..." "Yellow"
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
}
finally {
    Write-LogLine "Supervisor shutting down - killing tunnel processes..." "Yellow"
    if ($script:ChildProc -and -not $script:ChildProc.HasExited) {
        Stop-ProcessTree -ProcessId $script:ChildProc.Id -Reason "supervisor exit"
    }
    Stop-ExistingTunnels -Quiet
    Exit-TunnelMutex
}
