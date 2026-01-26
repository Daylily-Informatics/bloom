"""GUI/Web UI commands for BLOOM CLI."""

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent


@click.command()
@click.option('--port', '-p', default=8080, type=int, help='Port to run on (default: 8080)')
@click.option('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
@click.option('--reload', '-r', is_flag=True, help='Enable auto-reload for development')
@click.option('--https', is_flag=True, help='Enable HTTPS (requires certs in certs/)')
def gui(port, host, reload, https):
    """Start the BLOOM web UI."""
    console.print(f"[cyan]Starting BLOOM UI on {host}:{port}...[/cyan]")

    # Build uvicorn command
    cmd = [
        sys.executable, "-m", "uvicorn",
        "main:app",
        "--host", host,
        "--port", str(port),
    ]
    
    if reload:
        cmd.append("--reload")
    
    if https:
        certs_dir = PROJECT_ROOT / "certs"
        key_file = certs_dir / "key.pem"
        cert_file = certs_dir / "cert.pem"
        
        if not key_file.exists() or not cert_file.exists():
            console.print("[red]✗[/red] HTTPS certificates not found in certs/")
            console.print("   Generate with: [cyan]mkcert -key-file certs/key.pem -cert-file certs/cert.pem localhost 127.0.0.1[/cyan]")
            raise SystemExit(1)
        
        cmd.extend(["--ssl-keyfile", str(key_file), "--ssl-certfile", str(cert_file)])
        console.print(f"   HTTPS enabled")
    
    console.print(f"   URL: [cyan]{'https' if https else 'http'}://{host}:{port}[/cyan]")
    console.print()
    
    # Run uvicorn
    os.chdir(PROJECT_ROOT)
    os.execvp(sys.executable, cmd)

