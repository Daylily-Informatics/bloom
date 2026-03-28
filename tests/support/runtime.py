"""Shared pytest runtime/bootstrap helpers for BLOOM integration suites."""

from __future__ import annotations

import os
import secrets
import socket
import tempfile
from pathlib import Path

INTEGRATION_TEST_FILES = frozenset(
    {
        "test_api_v1.py",
        "test_gui_endpoints.py",
        "test_route_coverage_gaps_api.py",
        "test_route_coverage_gaps_gui.py",
    }
)

TEST_COGNITO_ENV_DEFAULTS = {
    "BLOOM_AUTH__COGNITO_USER_POOL_ID": "us-west-2_test-pool",
    "BLOOM_AUTH__COGNITO_CLIENT_ID": "bloom-test-client",
    "BLOOM_AUTH__COGNITO_DOMAIN": "bloom-test.auth.us-west-2.amazoncognito.com",
    "BLOOM_AUTH__COGNITO_REGION": "us-west-2",
    "BLOOM_AUTH__COGNITO_REDIRECT_URI": "https://localhost:8912/auth/callback",
    "BLOOM_AUTH__COGNITO_LOGOUT_REDIRECT_URI": "https://localhost:8912/",
}


def tapdb_config_path_needs_bootstrap(path_value: str | None) -> bool:
    """Return True when the current TAPDB_CONFIG_PATH should be replaced for tests."""
    if not str(path_value or "").strip():
        return True
    return not Path(path_value).expanduser().is_file()


def create_temp_tapdb_config(
    *, local_port: str | None = None, user: str | None = None
) -> Path:
    """Create a deterministic local TapDB namespaced config for tests."""
    resolved_port = str(
        local_port or os.environ.get("BLOOM_TAPDB_LOCAL_PG_PORT") or "5566"
    ).strip()
    resolved_user = str(user or os.environ.get("USER") or "postgres").strip()
    tmp_path = (
        Path(tempfile.gettempdir()) / f"bloom_tapdb_config_{secrets.token_hex(16)}.yaml"
    )
    tmp_path.write_text(
        "\n".join(
            [
                "meta:",
                "  config_version: 2",
                "  client_id: bloom",
                "  database_name: bloom",
                "environments:",
                "  dev:",
                "    engine_type: local",
                "    host: localhost",
                f'    port: "{resolved_port}"',
                '    ui_port: "8912"',
                f'    user: "{resolved_user}"',
                '    password: ""',
                '    database: "tapdb_bloom_dev"',
                '    cognito_user_pool_id: "us-west-2_test-pool"',
                '    audit_log_euid_prefix: "TAG"',
                '    support_email: "support@dyly.bio"',
                "  test:",
                "    engine_type: local",
                "    host: localhost",
                f'    port: "{resolved_port}"',
                '    ui_port: "8912"',
                f'    user: "{resolved_user}"',
                '    password: ""',
                '    database: "tapdb_bloom_test"',
                '    cognito_user_pool_id: "us-west-2_test-pool"',
                '    audit_log_euid_prefix: "TAG"',
                '    support_email: "support@dyly.bio"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    os.chmod(tmp_path, 0o600)
    return tmp_path


def ensure_test_runtime_environment() -> Path:
    """Prepare deterministic env/config needed for strict app startup in tests."""
    os.environ.setdefault("TAPDB_CLIENT_ID", "bloom")
    os.environ.setdefault("TAPDB_DATABASE_NAME", "bloom")
    os.environ.setdefault("TAPDB_STRICT_NAMESPACE", "1")

    for key, value in TEST_COGNITO_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)

    current_path = os.environ.get("TAPDB_CONFIG_PATH")
    if tapdb_config_path_needs_bootstrap(current_path):
        config_path = create_temp_tapdb_config()
        os.environ["TAPDB_CONFIG_PATH"] = str(config_path)
    else:
        config_path = Path(str(current_path)).expanduser()

    os.environ.setdefault(
        "PGPORT", str(os.environ.get("BLOOM_TAPDB_LOCAL_PG_PORT") or "5566")
    )
    os.environ.setdefault("ECHO_SQL", "False")
    os.environ["BLOOM_DISABLE_RATE_LIMITING"] = "1"
    os.environ.setdefault("BLOOM_RATE_LIMIT", "no")

    from bloom_lims.config import get_settings

    get_settings.cache_clear()
    return config_path


def selected_items_need_local_tapdb(items: list[object]) -> bool:
    """Return True when the selected pytest items include DB-backed API/GUI suites."""
    for item in items:
        path = getattr(item, "fspath", None)
        if path is None:
            continue
        if Path(str(path)).name in INTEGRATION_TEST_FILES:
            return True
    return False


def tapdb_local_available(*, env_name: str = "dev") -> bool:
    """Return True when the configured local TapDB Postgres endpoint accepts TCP connections."""
    ensure_test_runtime_environment()

    from bloom_lims.config import get_tapdb_db_config

    config = get_tapdb_db_config(env_name=env_name)
    host = str(config.get("host") or "localhost").strip()
    port = int(config.get("port") or os.environ.get("PGPORT") or "5566")

    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def ensure_local_tapdb_ready(*, env_name: str = "dev") -> bool:
    """Bootstrap local TapDB via the Bloom CLI when DB-backed integration suites need it."""
    ensure_test_runtime_environment()
    if tapdb_local_available(env_name=env_name):
        return False

    from bloom_lims.cli import db as db_commands

    try:
        db_commands.db_init(force=False)
    except SystemExit as exc:
        raise RuntimeError(f"`bloom db init` exited with status {exc.code}") from exc
    except Exception as exc:
        raise RuntimeError(f"`bloom db init` failed: {exc}") from exc

    if not tapdb_local_available(env_name=env_name):
        raise RuntimeError(
            "Local TapDB is still unavailable after `bloom db init`. "
            "Fix the runtime and retry `source bloom_activate.sh && bloom db init`."
        )

    return True
