"""Server lifecycle commands for the Bloom CLI."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli_core_yo.registry import CommandRegistry
    from cli_core_yo.spec import CliSpec

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import typer
from cli_core_yo.certs import resolve_https_certs, shared_dayhoff_certs_dir
from cli_core_yo.server import (
    display_host,
    latest_log,
    new_log_path,
    read_pid,
    stop_pid,
    write_pid,
)
from rich.console import Console

from bloom_lims.config import (
    DEFAULT_BLOOM_WEB_PORT,
    apply_runtime_environment,
    atlas_webhook_secret_warning,
    get_settings,
    get_tapdb_db_config,
)

server_app = typer.Typer(help="Server lifecycle commands.", no_args_is_help=True)
console = Console()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TAPDB_LOG_DIR = Path.home() / ".config" / "tapdb" / "logs"
SERVER_META_FILE = "server-meta.json"


class LogService(str, Enum):
    server = "server"
    tapdb = "tapdb"
    all = "all"


def _state_dir() -> Path:
    """Return the Bloom XDG state directory."""
    try:
        from cli_core_yo.runtime import get_context

        return get_context().xdg_paths.state
    except Exception:
        return Path.home() / ".local" / "state" / "bloom"


def _log_dir() -> Path:
    return _state_dir() / "logs"


def _pid_file() -> Path:
    return _state_dir() / "server.pid"


def _runtime_meta_file() -> Path:
    return _state_dir() / SERVER_META_FILE


def _ensure_dir() -> None:
    _state_dir().mkdir(parents=True, exist_ok=True)
    _log_dir().mkdir(parents=True, exist_ok=True)


def _latest_server_log() -> Path | None:
    return latest_log(_log_dir())


def active_server_pid() -> tuple[int | None, Path]:
    pid_file = _pid_file()
    return read_pid(pid_file), pid_file


def server_status_label() -> str:
    pid, _ = active_server_pid()
    if pid is None:
        return "Stopped"
    return f"Running ({_runtime_scheme().upper()}, PID {pid})"


def _runtime_host_and_port(default_port: int, default_host: str) -> tuple[str, int]:
    host = os.environ.get(
        "BLOOM_RUNTIME__HOST", os.environ.get("BLOOM_HOST", default_host)
    )
    port = int(
        os.environ.get(
            "BLOOM_RUNTIME__PORT", os.environ.get("BLOOM_PORT", str(default_port))
        )
    )
    return host, port


def _deployment_shared_certs_dir() -> Path:
    from bloom_lims.config import _resolve_deployment_code

    return shared_dayhoff_certs_dir(_resolve_deployment_code())


def _write_runtime_meta(*, ssl_enabled: bool) -> None:
    _runtime_meta_file().write_text(
        json.dumps({"ssl_enabled": ssl_enabled}, sort_keys=True),
        encoding="utf-8",
    )


def _read_runtime_meta() -> dict[str, object]:
    meta_file = _runtime_meta_file()
    if not meta_file.exists():
        return {}
    try:
        payload = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _clear_runtime_meta() -> None:
    _runtime_meta_file().unlink(missing_ok=True)


def _runtime_scheme() -> str:
    meta = _read_runtime_meta()
    if str(meta.get("ssl_enabled")).lower() in {"false", "0", "no"}:
        return "http"
    if str(meta.get("ssl_enabled")).lower() in {"true", "1", "yes"}:
        return "https"
    return "https"


@server_app.command("start")
def start(
    port: int = typer.Option(
        DEFAULT_BLOOM_WEB_PORT, "--port", "-p", help="Port to run on"
    ),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),  # nosec B104
    reload: bool = typer.Option(
        False, "--reload", "-r", help="Enable auto-reload for development"
    ),
    background: bool = typer.Option(
        True,
        "--background/--foreground",
        "-b/-f",
        help="Run in background",
    ),
    ssl: bool = typer.Option(
        True,
        "--ssl/--no-ssl",
        help="Serve over HTTPS with deployment-scoped certs",
    ),
    cert: str | None = typer.Option(None, "--cert", help="TLS certificate file"),
    key: str | None = typer.Option(None, "--key", help="TLS private key file"),
) -> None:
    """Start the BLOOM web UI."""
    _ensure_dir()
    host, port = _runtime_host_and_port(port, host)
    shown_host = display_host(host)
    if not ssl and (cert or key):
        console.print("[red]✗[/red] --cert and --key require HTTPS; omit them with --no-ssl")
        raise typer.Exit(1)

    protocol = "https" if ssl else "http"
    cert_file = key_file = None
    if ssl:
        resolved = resolve_https_certs(
            cert_path=cert,
            key_path=key,
            shared_certs_dir=_deployment_shared_certs_dir(),
            fallback_certs_dir=PROJECT_ROOT / "certs",
        )
        cert_file = resolved.cert_path
        key_file = resolved.key_path

    try:
        settings = get_settings()
        apply_runtime_environment(settings)
    except Exception as exc:
        console.print(f"[red]✗[/red] Failed to apply runtime environment: {exc}")
        raise typer.Exit(1) from exc

    preflight_errors: list[str] = []

    try:
        get_tapdb_db_config()
    except Exception as exc:
        preflight_errors.append(f"TapDB config: {exc}")

    auth = settings.auth
    if not auth.cognito_user_pool_id:
        preflight_errors.append("auth.cognito_user_pool_id is empty")
    if not auth.cognito_client_id:
        preflight_errors.append("auth.cognito_client_id is empty")
    if not auth.cognito_domain:
        preflight_errors.append("auth.cognito_domain is empty")
    if not auth.cognito_redirect_uri:
        preflight_errors.append("auth.cognito_redirect_uri is empty")

    if preflight_errors:
        console.print("[red]✗[/red] Startup aborted - missing required configuration:")
        for err in preflight_errors:
            console.print(f"   • {err}")
        console.print(
            "\n   Fix your config ([cyan]bloom config edit[/cyan]) or run [cyan]bloom db init[/cyan]."
        )
        raise typer.Exit(1)

    atlas_secret_warning = atlas_webhook_secret_warning(settings)
    if atlas_secret_warning:
        console.print(f"[yellow]⚠[/yellow] {atlas_secret_warning}")
        console.print(
            "   Configure it in [cyan]~/.config/bloom/config.yaml[/cyan] under "
            "[cyan]atlas.webhook_secret[/cyan]."
        )
        console.log(atlas_secret_warning)

    pid, _ = active_server_pid()
    if pid:
        console.print(f"[yellow]⚠[/yellow] Server already running (PID {pid})")
        console.print(f"   URL: [cyan]{protocol}://{shown_host}:{port}[/cyan]")
        console.print(
            "   Use [cyan]bloom server stop[/cyan] to stop or [cyan]bloom server logs[/cyan] to view logs"
        )
        return

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        cmd.append("--reload")
    if ssl and cert_file and key_file:
        cmd.extend(["--ssl-keyfile", str(key_file), "--ssl-certfile", str(cert_file)])

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    _write_runtime_meta(ssl_enabled=ssl)

    if background:
        log_file = new_log_path(_log_dir())
        with open(log_file, "w", buffering=1) as log_f:
            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=PROJECT_ROOT,
                env=env,
            )
            time.sleep(2)
            if proc.poll() is not None:
                _clear_runtime_meta()
                console.print("[red]✗[/red] Server failed to start. Check logs:")
                console.print(f"   [dim]{log_file}[/dim]")
                raise typer.Exit(1)
            write_pid(_pid_file(), proc.pid)
            console.print(f"[green]✓[/green] Server started (PID {proc.pid})")
            console.print(f"   URL: [cyan]{protocol}://{shown_host}:{port}[/cyan]")
            console.print(f"   Logs: [dim]{log_file}[/dim]")
            console.print(
                "   Use [cyan]bloom server logs[/cyan] to view logs or [cyan]bloom server stop[/cyan] to stop"
            )
        return

    console.print(f"[cyan]Starting BLOOM UI on {host}:{port}...[/cyan]")
    console.print(f"   URL: [cyan]{protocol}://{shown_host}:{port}[/cyan]")
    console.print("   Press Ctrl+C to stop\n")
    try:
        subprocess.run(cmd, env=env, cwd=PROJECT_ROOT)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠[/yellow] Server stopped")
    except Exception:
        _clear_runtime_meta()
        raise


@server_app.command("stop")
def stop() -> None:
    """Stop the BLOOM web UI."""
    stopped, msg = stop_pid(_pid_file())
    if stopped:
        _clear_runtime_meta()
        console.print(f"[green]✓[/green] {msg}")
    elif "Permission" in msg:
        console.print(f"[red]✗[/red] {msg}")
        raise typer.Exit(1)
    else:
        console.print(f"[yellow]⚠[/yellow] {msg}")


@server_app.command("status")
def status() -> None:
    """Show BLOOM server runtime status."""
    pid, _ = active_server_pid()
    host, port = _runtime_host_and_port(DEFAULT_BLOOM_WEB_PORT, "0.0.0.0")  # nosec B104
    shown_host = display_host(host)
    log_file = _latest_server_log()
    if pid:
        console.print(f"[green]●[/green] Server is [green]running[/green] (PID {pid})")
        console.print(f"   URL: [cyan]{_runtime_scheme()}://{shown_host}:{port}[/cyan]")
        if log_file:
            console.print(f"   Logs: [dim]{log_file}[/dim]")
        return

    console.print("[dim]○[/dim] Server is [dim]not running[/dim]")


@server_app.command("logs")
def logs(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    service: LogService = typer.Option(
        LogService.all, "--service", "-s", help="Service to show logs for"
    ),
) -> None:
    """View BLOOM and TapDB operation logs."""
    log_files: list[tuple[str, Path]] = []

    if service in {LogService.server, LogService.all}:
        server_log = _latest_server_log()
        if server_log:
            log_files.append(("Server", server_log))

    if service in {LogService.tapdb, LogService.all}:
        tapdb_log = TAPDB_LOG_DIR / "db_operations.log"
        if tapdb_log.exists():
            log_files.append(("TapDB", tapdb_log))

    if not log_files:
        console.print("[yellow]No log files found.[/yellow]")
        console.print(f"  • Server: [cyan]{_log_dir()}/server_*.log[/cyan]")
        console.print("  • TapDB: [cyan]~/.config/tapdb/logs/db_operations.log[/cyan]")
        return

    for name, log_file in log_files:
        console.print(f"[bold]{name} Logs[/bold]: {log_file}")
        console.print()
        if follow:
            console.print("[dim](Press Ctrl+C to stop)[/dim]")
            try:
                subprocess.run(["tail", "-f", "-n", str(lines), str(log_file)])
            except KeyboardInterrupt:
                console.print()
        else:
            subprocess.run(["tail", "-n", str(lines), str(log_file)])


def register(registry: CommandRegistry, spec: CliSpec) -> None:
    """cli-core-yo plugin: register the server command group."""
    registry.add_typer_app(None, server_app, "server", "Server lifecycle commands.")
