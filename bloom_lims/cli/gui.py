"""GUI/Web UI commands for BLOOM CLI."""

import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
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
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
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


def _ensure_https_certs() -> tuple[Path, Path]:
    """Ensure localhost TLS cert/key exist; generate with mkcert if missing."""
    certs_dir = PROJECT_ROOT / "certs"
    certs_dir.mkdir(parents=True, exist_ok=True)
    cert_file = certs_dir / "cert.pem"
    key_file = certs_dir / "key.pem"

    if cert_file.exists() and key_file.exists():
        return cert_file, key_file

    mkcert_bin = shutil.which("mkcert")
    if not mkcert_bin:
        console.print("[red]✗[/red]  mkcert is required to generate localhost HTTPS certificates.")
        raise SystemExit(1)

    try:
        subprocess.run(
            [mkcert_bin, "-install"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                mkcert_bin,
                "-key-file",
                str(key_file),
                "-cert-file",
                str(cert_file),
                "localhost",
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        console.print(f"[red]✗[/red]  Failed to generate HTTPS certificates with mkcert: {stderr}")
        raise SystemExit(1)

    if not (cert_file.exists() and key_file.exists()):
        console.print("[red]✗[/red]  mkcert did not produce cert.pem/key.pem in certs/")
        raise SystemExit(1)
    return cert_file, key_file


@click.command()
@click.option('--port', '-p', default=8912, type=int, help='Port to run on (default: 8912)')
@click.option('--reload', '-r', is_flag=True, help='Enable auto-reload for development')
@click.option('--background/--foreground', '-b/-f', default=True, help='Run in background (default)')
def gui(port, reload, background):
    """Start the BLOOM web UI."""
    _ensure_dir()
    host = "localhost"
    protocol = "https"
    cert_file, key_file = _ensure_https_certs()

    # Ensure TapDB namespace env vars are present even if the caller didn't
    # source bloom_activate.sh (strict namespace is the default policy).
    try:
        from bloom_lims.config import apply_runtime_environment, get_settings

        apply_runtime_environment(get_settings())
    except Exception as exc:
        console.print(f"[red]✗[/red]  Failed to apply runtime environment: {exc}")
        raise SystemExit(1)

    pid = _get_pid()
    if pid:
        console.print(f"[yellow]⚠[/yellow]  Server already running (PID {pid})")
        console.print(f"   URL: [cyan]{protocol}://{host}:{port}[/cyan]")
        console.print("   Use [cyan]bloom stop[/cyan] to stop or [cyan]bloom logs[/cyan] to view logs")
        return

    cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")
    cmd.extend(["--ssl-keyfile", str(key_file), "--ssl-certfile", str(cert_file)])

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
