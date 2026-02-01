"""GUI/Web UI commands for BLOOM CLI."""

import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

console = Console()

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# PID and log file locations
CONFIG_DIR = Path.home() / ".bloom"
LOG_DIR = CONFIG_DIR / "logs"
PID_FILE = CONFIG_DIR / "server.pid"


def _ensure_dir():
    """Ensure .bloom directories exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _get_log_file() -> Path:
    """Get timestamped log file path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / f"server_{ts}.log"


def _get_latest_log() -> Path | None:
    """Get the most recent log file."""
    logs = sorted(LOG_DIR.glob("server_*.log"), reverse=True)
    return logs[0] if logs else None


def _get_pid() -> int | None:
    """Get the running server PID if exists."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink(missing_ok=True)
    return None


@click.command()
@click.option('--port', '-p', default=8911, type=int, help='Port to run on (default: 8911)')
@click.option('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
@click.option('--reload', '-r', is_flag=True, help='Enable auto-reload for development')
@click.option('--https', is_flag=True, help='Enable HTTPS (requires certs in certs/)')
@click.option('--background/--foreground', '-b/-f', default=True, help='Run in background (default)')
def gui(port, host, reload, https, background):
    """Start the BLOOM web UI."""
    _ensure_dir()

    pid = _get_pid()
    if pid:
        protocol = "https" if https else "http"
        console.print(f"[yellow]⚠[/yellow]  Server already running (PID {pid})")
        console.print(f"   URL: [cyan]{protocol}://{host}:{port}[/cyan]")
        console.print("   Use [cyan]bloom stop[/cyan] to stop or [cyan]bloom logs[/cyan] to view logs")
        return

    cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")
    if https:
        certs_dir = PROJECT_ROOT / "certs"
        if not (certs_dir / "key.pem").exists():
            console.print("[red]✗[/red] HTTPS certificates not found in certs/")
            raise SystemExit(1)
        cmd.extend(["--ssl-keyfile", str(certs_dir / "key.pem"), "--ssl-certfile", str(certs_dir / "cert.pem")])

    protocol = "https" if https else "http"
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    if background:
        log_file = _get_log_file()
        with open(log_file, "w", buffering=1) as log_f:
            proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True, cwd=PROJECT_ROOT, env=env)
            time.sleep(2)
            if proc.poll() is not None:
                console.print("[red]✗[/red]  Server failed to start. Check logs:")
                console.print(f"   [dim]{log_file}[/dim]")
                raise SystemExit(1)
            PID_FILE.write_text(str(proc.pid))
            console.print(f"[green]✓[/green]  Server started (PID {proc.pid})")
            console.print(f"   URL: [cyan]{protocol}://{host}:{port}[/cyan]")
            console.print(f"   Logs: [dim]{log_file}[/dim]")
            console.print("   Use [cyan]bloom logs[/cyan] to view logs or [cyan]bloom stop[/cyan] to stop")
    else:
        console.print(f"[cyan]Starting BLOOM UI on {host}:{port}...[/cyan]")
        console.print(f"   URL: [cyan]{protocol}://{host}:{port}[/cyan]")
        console.print("   Press Ctrl+C to stop\n")
        os.chdir(PROJECT_ROOT)
        try:
            subprocess.run(cmd, env=env)
        except KeyboardInterrupt:
            console.print("\n[yellow]⚠[/yellow]  Server stopped")


@click.command()
def stop():
    """Stop the BLOOM web UI."""
    pid = _get_pid()
    if not pid:
        console.print("[yellow]⚠[/yellow]  No server running")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            os.kill(pid, signal.SIGKILL)
        PID_FILE.unlink(missing_ok=True)
        console.print(f"[green]✓[/green]  Server stopped (was PID {pid})")
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        console.print("[yellow]⚠[/yellow]  Server was not running")
    except PermissionError:
        console.print(f"[red]✗[/red]  Permission denied stopping PID {pid}")
        raise SystemExit(1)

