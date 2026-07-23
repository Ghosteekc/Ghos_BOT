"""Автозапуск localtunnel при старте бота (Windows)."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
TUNNEL_DIR = ROOT / "scripts" / "localtunnel"
TUNNEL_SCRIPT = TUNNEL_DIR / "start-tunnel.ps1"
DEFAULT_SUBDOMAIN = "ghosteekcr"


def _run_powershell(command: str) -> None:
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=str(TUNNEL_DIR),
        check=False,
        capture_output=True,
        text=True,
    )


def stop_existing_tunnels() -> None:
    """Остановить все процессы localtunnel (освободить subdomain)."""
    if sys.platform != "win32":
        return

    logger.info("Stopping existing localtunnel processes...")
    _run_powershell(
        r"""
        Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'localtunnel|lt\.js' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'localtunnel|lt\.js' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'start-tunnel\.ps1' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        """
    )
    time.sleep(2)


def wait_for_backend(port: int, *, timeout_sec: float = 45.0) -> bool:
    """Дождаться готовности FastAPI перед запуском туннеля."""
    deadline = time.monotonic() + timeout_sec
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    return False


def start_tunnel(
    *,
    subdomain: str = DEFAULT_SUBDOMAIN,
    port: int = 8080,
    skip_loca_lt_check: bool = False,
) -> subprocess.Popen[str] | None:
    """Запустить start-tunnel.ps1 в фоне с фиксированным subdomain."""
    if sys.platform != "win32":
        logger.warning("Tunnel auto-start is supported only on Windows")
        return None

    if not TUNNEL_SCRIPT.exists():
        logger.error("Tunnel script not found: %s", TUNNEL_SCRIPT)
        return None

    if not wait_for_backend(port):
        logger.warning(
            "Backend is not ready on :%s — tunnel supervisor will wait for API",
            port,
        )

    stop_existing_tunnels()

    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-NoExit",
        "-File",
        str(TUNNEL_SCRIPT),
        "-Port",
        str(port),
        "-Subdomain",
        subdomain,
    ]
    if skip_loca_lt_check:
        args.append("-SkipLocaLtCheck")

    logger.info("Starting localtunnel supervisor -> https://%s.loca.lt", subdomain)
    proc = subprocess.Popen(
        args,
        cwd=str(TUNNEL_DIR),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    logger.info(
        "Localtunnel supervisor started (PID %s). Watch the tunnel window or %s",
        proc.pid,
        TUNNEL_DIR / "tunnel.log",
    )
    return proc


def stop_tunnel_process(proc: subprocess.Popen[str] | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    stop_existing_tunnels()
