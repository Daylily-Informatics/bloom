"""GUI/Web UI commands for BLOOM CLI."""

import os
import subprocess
import sys
import time
from pathlib import Path

import click
from cli_core_yo.certs import ensure_certs
from cli_core_yo.oauth import runtime_oauth_host, validate_uri_list_ports
from cli_core_yo.server import (
    display_host,
    latest_log,
    list_logs,
    new_log_path,
    read_pid,
    stop_pid,
    write_pid,
)
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


def _validate_cognito_uris_for_port(port: int, host: str) -> None:
    """Warn if Cognito callback/logout env vars don't match the runtime port."""
    oauth_host = runtime_oauth_host(host)
    uris_to_check = [
        (os.environ.get("COGNITO_CALLBACK_URL", ""), "COGNITO_CALLBACK_URL"),
        (os.environ.get("COGNITO_LOGOUT_URL", ""), "COGNITO_LOGOUT_URL"),
    ]
    all_errors: list[str] = []
    for uri, label in uris_to_check:
        if not uri:
            continue
        errors = validate_uri_list_ports(
            uris=[uri],
            label=label,
            expected_port=port,
            runtime_host=oauth_host,
        )
        all_errors.extend(errors)

    if all_errors:
        console.print("[yellow]⚠[/yellow]  Cognito URI port mismatches detected:")
        for err in all_errors:
            console.print(f"   • {err}")
        console.print(f"   Server is starting on port [cyan]{port}[/cyan]")
        console.print("")



@click.command()
@click.option('--port', '-p', default=8912, type=int, help='Port to run on (default: 8912)')
@click.option('--host', '-h', default='0.0.0.0', type=str, help='Host to bind to (default: 0.0.0.0)')
@click.option('--reload', '-r', is_flag=True, help='Enable auto-reload for development')
@click.option('--background/--foreground', '-b/-f', default=True, help='Run in background (default)')
def gui(port, host, reload, background):
    """Start the BLOOM web UI."""
    _ensure_dir()
    port = int(os.environ.get("BLOOM_RUNTIME__PORT", os.environ.get("BLOOM_PORT", str(port))))
    host = os.environ.get("BLOOM_RUNTIME__HOST", os.environ.get("BLOOM_HOST", "0.0.0.0"))
    display_host = "localhost" if host in ("0.0.0.0", "::") else host
    protocol = "https"
    cert_file, key_file = ensure_certs(PROJECT_ROOT / "certs")

    # Ensure TapDB namespace env vars are present even if the caller didn't
    # source bloom_activate.sh (strict namespace is the default policy).
    try:
        from bloom_lims.config import apply_runtime_environment, get_settings

        settings = get_settings()
        apply_runtime_environment(settings)
    except Exception as exc:
        console.print(f"[red]✗[/red]  Failed to apply runtime environment: {exc}")
        raise SystemExit(1)

    # ── Fail hard if critical configs are missing ──────────────────────
    _preflight_errors: list[str] = []

    # TapDB config must be resolvable
    try:
        from bloom_lims.config import get_tapdb_db_config

        get_tapdb_db_config()
    except Exception as exc:
        _preflight_errors.append(f"TapDB config: {exc}")

    # Cognito auth must be configured (pool + client + domain + redirect)
    _auth = settings.auth
    if not _auth.cognito_user_pool_id:
        _preflight_errors.append("auth.cognito_user_pool_id is empty")
    if not _auth.cognito_client_id:
        _preflight_errors.append("auth.cognito_client_id is empty")
    if not _auth.cognito_domain:
        _preflight_errors.append("auth.cognito_domain is empty")
    if not _auth.cognito_redirect_uri:
        _preflight_errors.append("auth.cognito_redirect_uri is empty")

    if _preflight_errors:
        console.print("[red]✗[/red]  Startup aborted — missing required configuration:")
        for err in _preflight_errors:
            console.print(f"   • {err}")
        console.print("\n   Fix your config ([cyan]bloom config -e[/cyan]) or run [cyan]bloom db init[/cyan].")
        raise SystemExit(1)

    pid = _get_pid()
    if pid:
        console.print(f"[yellow]⚠[/yellow]  Server already running (PID {pid})")
        console.print(f"   URL: [cyan]{protocol}://{display_host}:{port}[/cyan]")
        console.print("   Use [cyan]bloom stop[/cyan] to stop or [cyan]bloom logs[/cyan] to view logs")
        return

    cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")
    cmd.extend(["--ssl-keyfile", str(key_file), "--ssl-certfile", str(cert_file)])

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    if background:
        log_file = new_log_path(LOG_DIR)
        with open(log_file, "w", buffering=1) as log_f:
            proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True, cwd=PROJECT_ROOT, env=env)
            time.sleep(2)
            if proc.poll() is not None:
                console.print("[red]✗[/red]  Server failed to start. Check logs:")
                console.print(f"   [dim]{log_file}[/dim]")
                raise SystemExit(1)
            write_pid(PID_FILE, proc.pid)
            console.print(f"[green]✓[/green]  Server started (PID {proc.pid})")
            console.print(f"   URL: [cyan]{protocol}://{display_host}:{port}[/cyan]")
            console.print(f"   Logs: [dim]{log_file}[/dim]")
            console.print("   Use [cyan]bloom logs[/cyan] to view logs or [cyan]bloom stop[/cyan] to stop")
    else:
        console.print(f"[cyan]Starting BLOOM UI on {host}:{port}...[/cyan]")
        console.print(f"   URL: [cyan]{protocol}://{display_host}:{port}[/cyan]")
        console.print("   Press Ctrl+C to stop\n")
        os.chdir(PROJECT_ROOT)
        try:
            subprocess.run(cmd, env=env)
        except KeyboardInterrupt:
            console.print("\n[yellow]⚠[/yellow]  Server stopped")


@click.command()
def stop():
    """Stop the BLOOM web UI."""
    stopped, msg = stop_pid(PID_FILE)
    if stopped:
        console.print(f"[green]✓[/green]  {msg}")
    elif "Permission" in msg:
        console.print(f"[red]✗[/red]  {msg}")
        raise SystemExit(1)
    else:
        console.print(f"[yellow]⚠[/yellow]  {msg}")
