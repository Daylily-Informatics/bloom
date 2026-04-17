"""Shared pytest runtime/bootstrap helpers for BLOOM integration suites."""

from __future__ import annotations

import json
import os
import secrets
import socket
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from functools import lru_cache

from packaging.requirements import Requirement

from bloom_lims.config import (
    DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT,
    DEFAULT_BLOOM_WEB_PORT,
)

INTEGRATION_TEST_FILES = frozenset(
    {
        "test_admin_auth.py",
        "test_api_v1.py",
        "test_api_auth_rbac.py",
        "test_beta_cross_repo_smoke.py",
        "test_beta_lab.py",
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
    "BLOOM_AUTH__COGNITO_REDIRECT_URI": f"https://localhost:{DEFAULT_BLOOM_WEB_PORT}/auth/callback",
    "BLOOM_AUTH__COGNITO_LOGOUT_REDIRECT_URI": f"https://localhost:{DEFAULT_BLOOM_WEB_PORT}/",
}

_BLOOM_TEMPLATE_CONFIG = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "tapdb_templates"
    / "bloom"
    / "templates.json"
)
_TAPDB_CORE_PREFIX_OWNERSHIP = {
    "TPX",
    "EDG",
    "ADT",
    "SYS",
    "MSG",
}
_PREFIX_OWNERSHIP_OWNER_FIELD = "".join(("issuer", "_app_code"))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_TOML = PROJECT_ROOT / "pyproject.toml"


def tapdb_config_path_needs_bootstrap(path_value: str | None) -> bool:
    """Return True when the configured Bloom TapDB config path should be replaced for tests."""
    if not str(path_value or "").strip():
        return True
    return not Path(path_value).expanduser().is_file()


def _load_bloom_template_prefixes() -> set[str]:
    try:
        payload = json.loads(_BLOOM_TEMPLATE_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(payload, dict):
        payload = payload.get("templates", [])
    if not isinstance(payload, list):
        return set()
    prefixes: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        prefix = str(entry.get("instance_prefix") or "").strip().upper()
        if prefix:
            prefixes.add(prefix)
    return prefixes


@lru_cache()
def read_pyproject_dependency_spec(package_name: str) -> str:
    if not PYPROJECT_TOML.exists():
        raise RuntimeError(f"pyproject.toml not found at {PYPROJECT_TOML}")

    payload = tomllib.loads(PYPROJECT_TOML.read_text(encoding="utf-8"))
    dependencies = (
        payload.get("project", {}).get("dependencies", [])
        if isinstance(payload, dict)
        else []
    )
    if not isinstance(dependencies, list):
        raise RuntimeError("pyproject.toml project.dependencies must be a list")

    for entry in dependencies:
        try:
            requirement = Requirement(str(entry))
        except Exception:
            continue
        if requirement.name == package_name:
            return str(requirement.specifier)

    raise RuntimeError(f"Dependency {package_name!r} is not declared in pyproject.toml")


def read_pyproject_pinned_version(package_name: str) -> str:
    spec = read_pyproject_dependency_spec(package_name)
    if not spec.startswith("=="):
        raise RuntimeError(
            f"Dependency {package_name!r} is not pinned with an exact version: {spec}"
        )
    return spec.removeprefix("==")


def _write_registry_files(base_dir: Path) -> tuple[Path, Path]:
    domain_registry_path = base_dir / "domain_code_registry.json"
    prefix_registry_path = base_dir / "prefix_ownership_registry.json"
    domain_registry_path.write_text(
        json.dumps(
            {
                "version": "0.4.0",
                "domains": {
                    "Z": {"name": "localhost"},
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    bloom_prefixes = _load_bloom_template_prefixes()
    ownership = {
        "Z": {
            prefix: {_PREFIX_OWNERSHIP_OWNER_FIELD: "bloom"}
            for prefix in sorted(bloom_prefixes)
        }
    }
    for prefix in sorted(_TAPDB_CORE_PREFIX_OWNERSHIP):
        ownership["Z"][prefix] = {_PREFIX_OWNERSHIP_OWNER_FIELD: "daylily-tapdb"}

    prefix_registry_path.write_text(
        json.dumps(
            {
                "version": "0.4.0",
                "ownership": ownership,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return domain_registry_path, prefix_registry_path


def create_temp_tapdb_config(
    *, local_port: str | None = None, user: str | None = None
) -> Path:
    """Create a deterministic local TapDB namespaced config for tests."""
    resolved_port = str(
        local_port
        or os.environ.get("BLOOM_TAPDB_LOCAL_PG_PORT")
        or DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT
    ).strip()
    resolved_user = str(user or os.environ.get("USER") or "postgres").strip()
    tmp_path = (
        Path(tempfile.gettempdir()) / f"bloom_tapdb_config_{secrets.token_hex(16)}.yaml"
    )
    registry_base = (
        Path(tempfile.gettempdir()) / f"bloom_tapdb_registry_{secrets.token_hex(8)}"
    )
    registry_base.mkdir(parents=True, exist_ok=True)
    domain_registry_path, prefix_registry_path = _write_registry_files(registry_base)
    os.environ["TAPDB_DOMAIN_REGISTRY_PATH"] = str(domain_registry_path)
    os.environ["TAPDB_PREFIX_OWNERSHIP_REGISTRY_PATH"] = str(prefix_registry_path)
    os.environ["BLOOM_TAPDB__DOMAIN_REGISTRY_PATH"] = str(domain_registry_path)
    os.environ["BLOOM_TAPDB__PREFIX_OWNERSHIP_REGISTRY_PATH"] = str(
        prefix_registry_path
    )
    tmp_path.write_text(
        "\n".join(
            [
                "meta:",
                "  config_version: 3",
                "  client_id: bloom",
                "  database_name: bloom",
                "  owner_repo_name: bloom",
                f"  domain_registry_path: {domain_registry_path}",
                f"  prefix_ownership_registry_path: {prefix_registry_path}",
                "environments:",
                "  dev:",
                "    engine_type: local",
                "    host: localhost",
                f'    port: "{resolved_port}"',
                f'    ui_port: "{DEFAULT_BLOOM_WEB_PORT}"',
                f'    user: "{resolved_user}"',
                '    password: ""',
                '    database: "tapdb_bloom_dev"',
                '    domain_code: "Z"',
                '    cognito_user_pool_id: "us-west-2_test-pool"',
                '    audit_log_euid_prefix: "BGX"',
                '    support_email: "support@dyly.bio"',
                "  test:",
                "    engine_type: local",
                "    host: localhost",
                f'    port: "{resolved_port}"',
                f'    ui_port: "{DEFAULT_BLOOM_WEB_PORT}"',
                f'    user: "{resolved_user}"',
                '    password: ""',
                '    database: "tapdb_bloom_test"',
                '    domain_code: "Z"',
                '    cognito_user_pool_id: "us-west-2_test-pool"',
                '    audit_log_euid_prefix: "BGX"',
                '    support_email: "support@dyly.bio"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    os.chmod(tmp_path, 0o600)
    return tmp_path


def ensure_test_runtime_environment() -> Path:
    """Prepare deterministic Bloom config needed for strict app startup in tests."""
    os.environ["MERIDIAN_ENVIRONMENT"] = "production"
    os.environ["MERIDIAN_SANDBOX_PREFIX"] = ""
    os.environ["MERIDIAN_DOMAIN_CODE"] = "Z"
    os.environ["TAPDB_OWNER_REPO"] = "bloom"
    os.environ["TAPDB_DOMAIN_CODE"] = "Z"
    os.environ["BLOOM_TAPDB__CLIENT_ID"] = "bloom"
    os.environ["BLOOM_TAPDB__DATABASE_NAME"] = "bloom"
    os.environ["BLOOM_TAPDB__OWNER_REPO_NAME"] = "bloom"
    os.environ["BLOOM_TAPDB__DOMAIN_CODE"] = "Z"
    os.environ["BLOOM_TAPDB__STRICT_NAMESPACE"] = "1"
    os.environ["BLOOM_TAPDB__LOCAL_PG_PORT"] = str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT)

    for key, value in TEST_COGNITO_ENV_DEFAULTS.items():
        os.environ[key] = value

    config_path = create_temp_tapdb_config()
    os.environ["BLOOM_TAPDB__CONFIG_PATH"] = str(config_path)

    os.environ.setdefault("ECHO_SQL", "False")
    os.environ["BLOOM_DISABLE_RATE_LIMITING"] = "1"
    os.environ["BLOOM_RATE_LIMIT"] = "no"

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
    port = int(
        config.get("port")
        or os.environ.get("BLOOM_TAPDB__LOCAL_PG_PORT")
        or DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT
    )

    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def ensure_local_tapdb_ready(*, env_name: str = "dev") -> bool:
    """Bootstrap local TapDB via the Bloom CLI when DB-backed integration suites need it."""
    ensure_test_runtime_environment()
    started_local = False
    if tapdb_local_available(env_name=env_name):
        started_local = False
    else:
        from bloom_lims.cli import db as db_commands

        try:
            db_commands.db_build(force=False, target="local")
        except SystemExit as exc:
            raise RuntimeError(
                f"`bloom db build --target local` exited with status {exc.code}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"`bloom db build --target local` failed: {exc}"
            ) from exc

        started_local = True

    if not tapdb_local_available(env_name=env_name):
        raise RuntimeError(
            "Local TapDB is still unavailable after `bloom db build --target local`. "
            "Fix the runtime and retry `source ./activate <deploy-name> && bloom db build --target local`."
        )

    from bloom_lims.cli import db as db_commands

    try:
        db_commands.db_seed()
    except SystemExit as exc:
        raise RuntimeError(f"`bloom db seed` exited with status {exc.code}") from exc
    except Exception as exc:
        raise RuntimeError(f"`bloom db seed` failed: {exc}") from exc

    return started_local
