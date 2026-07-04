# Stable localtunnel to bot on :8080
# Run in a SEPARATE Windows PowerShell window - NOT in Cursor terminal.
#
# Examples:
#   .\start-tunnel.ps1
#   .\start-tunnel.ps1 -Subdomain ghosteekcr

param(
    [int]$Port = 8080,
    [string]$Subdomain = ""
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
    param([string]$Url)
    if (-not $Url) { return $false }
    if (-not (Test-SubdomainUrl -Url $Url)) {
        return $false
    }
    Set-Content -Path $UrlFile -Value $Url -Encoding UTF8
    Write-LogLine "Tunnel URL: $Url" "Green"
    Write-LogLine "Saved to: $UrlFile" "DarkGray"
    return $true
}

function Read-ProcessLines {
    param(
        [System.Diagnostics.Process]$Process,
        [ref]$SavedUrl,
        [ref]$WrongSubdomain
    )

    foreach ($stream in @($Process.StandardOutput, $Process.StandardError)) {
        while ($stream.Peek() -ge 0) {
            $line = $stream.ReadLine()
            if (-not $line) { continue }
            Write-LogLine $line
            if ($line -match "(https://[\w-]+\.loca\.lt)") {
                $url = $Matches[1]
                if ($SavedUrl.Value) { continue }
                if (Test-SubdomainUrl -Url $url) {
                    if (Save-TunnelUrl -Url $url) {
                        $SavedUrl.Value = $true
                    }
                } else {
                    Write-LogLine "Subdomain '$Subdomain' busy - got random URL: $url" "Red"
                    Write-LogLine "Killing wrong tunnel, will retry for ghosteekcr..." "Yellow"
                    $WrongSubdomain.Value = $true
                    return
                }
            }
        }
    }
}

function Start-LocalTunnelSession {
    param([string[]]$Arguments)

    $argText = ($Arguments | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }) -join " "

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "cmd.exe"
    $psi.Arguments = "/c npx $argText"
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $null = $proc.Start()

    $savedUrl = [ref]$false
    $wrongSubdomain = [ref]$false

    while (-not $proc.HasExited) {
        Read-ProcessLines -Process $proc -SavedUrl $savedUrl -WrongSubdomain $wrongSubdomain
        if ($wrongSubdomain.Value) {
            try {
                Write-LogLine "Stopping wrong tunnel (PID $($proc.Id))..." "Yellow"
                $proc.Kill()
                $proc.WaitForExit(5000)
            } catch {}
            Stop-ExistingTunnels
            return @{
                ExitCode = -1
                WrongSubdomain = $true
                SavedUrl = $savedUrl.Value
            }
        }
        Start-Sleep -Milliseconds 150
    }

    Read-ProcessLines -Process $proc -SavedUrl $savedUrl -WrongSubdomain $wrongSubdomain

    if ($wrongSubdomain.Value) {
        Stop-ExistingTunnels
        return @{
            ExitCode = -1
            WrongSubdomain = $true
            SavedUrl = $savedUrl.Value
        }
    }

    return @{
        ExitCode = $proc.ExitCode
        WrongSubdomain = $false
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
    Write-LogLine "Vercel VITE_API_URL=https://$Subdomain.loca.lt (set once, no redeploy on restart)" "Cyan"
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
    $session = Start-LocalTunnelSession -Arguments $ltArgs

    if ($session.WrongSubdomain) {
        $reclaimAttempt++
        $waitSec = [Math]::Min(30 + ($reclaimAttempt * 15), 90)
        Write-LogLine "Reclaim attempt $reclaimAttempt failed. Waiting $waitSec sec for loca.lt to release '$Subdomain'..." "Yellow"
        Stop-ExistingTunnels
        Start-Sleep -Seconds $waitSec
        continue
    }

    $reclaimAttempt = 0
    $restartDelay = if ($Subdomain) { 45 } else { 5 }
    Write-LogLine "Tunnel exited (code $($session.ExitCode)). Restart in $restartDelay sec..." "Yellow"
    Stop-ExistingTunnels
    Start-Sleep -Seconds $restartDelay
}
