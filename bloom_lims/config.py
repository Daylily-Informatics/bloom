"""
BLOOM LIMS Configuration Management.

Configuration precedence (highest to lowest):
1. Environment variables (BLOOM_* prefix)
2. User config file (~/.config/bloom-<deployment>/bloom-config-<deployment>.yaml)
3. Template defaults
"""

import colorsys
import hashlib
import importlib.metadata
import json
import logging
import os
import re
import secrets
import string
import tempfile
import tomllib
from functools import lru_cache
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import (
    PydanticBaseSettingsSource,
    YamlConfigSettingsSource,
)

from bloom_lims.domain_access import APPROVED_WEB_DOMAIN_SUFFIXES

logger = logging.getLogger(__name__)

DEFAULT_BLOOM_WEB_PORT = 8912
DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT = 5566
DEFAULT_BLOOM_CONDA_ENV_BASE = "BLOOM"
LEGACY_UPLOAD_DIR = "/var/lib/bloom/uploads"
DEFAULT_TAPDB_OWNER_REPO_NAME = "bloom"
DEFAULT_TAPDB_DOMAIN_CODE = "Z"
_CONFIG_FILE_OVERRIDE_ENV = "BLOOM_CONFIG_PATH"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_TOML = PROJECT_ROOT / "pyproject.toml"

TEMPLATE_CONFIG_FILE = (
    Path(__file__).resolve().parent / "etc" / "bloom-config-template.yaml"
)
DEFAULT_DEPLOYMENT_BANNER_COLOR = "#AFEEEE"
PRODUCTION_DEPLOYMENT_NAMES = {"prod", "production"}
SENSITIVE_CONFIG_KEYWORDS = (
    "secret",
    "token",
    "password",
    "passwd",
    "key",
    "credential",
    "private",
    "signing",
    "session",
    "cookie",
    "authorization",
    "client_secret",
    "api_key",
    "access_key",
    "secret_key",
)
CONFIG_UNSET = "<unset>"
CONFIG_REDACTED = "<redacted>"


def _sanitize_deployment_code(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9-]+", "-", cleaned)
    cleaned = cleaned.strip("-")
    return cleaned or "local"


def _resolve_deployment_code() -> str:
    env_candidates = (
        os.environ.get("BLOOM_DEPLOYMENT_CODE")
        or os.environ.get("DEPLOYMENT_CODE")
        or os.environ.get("LSMC_DEPLOYMENT_CODE")
    )
    if env_candidates:
        return _sanitize_deployment_code(env_candidates)

    conda_env = (os.environ.get("CONDA_DEFAULT_ENV") or "").strip()
    if conda_env:
        if conda_env.startswith(f"{DEFAULT_BLOOM_CONDA_ENV_BASE}-"):
            return _sanitize_deployment_code(
                conda_env.removeprefix(f"{DEFAULT_BLOOM_CONDA_ENV_BASE}-")
            )
        if conda_env != "base":
            return _sanitize_deployment_code(conda_env)

    conda_prefix = (os.environ.get("CONDA_PREFIX") or "").strip()
    if conda_prefix:
        env_name = Path(conda_prefix).name
        if env_name.startswith(f"{DEFAULT_BLOOM_CONDA_ENV_BASE}-"):
            return _sanitize_deployment_code(
                env_name.removeprefix(f"{DEFAULT_BLOOM_CONDA_ENV_BASE}-")
            )
        if env_name and env_name != "base":
            return _sanitize_deployment_code(env_name)

    return "local"


def _explicit_config_file_override() -> Path | None:
    raw = str(os.environ.get(_CONFIG_FILE_OVERRIDE_ENV) or "").strip()
    if not raw:
        return None
    if raw.startswith("~"):
        raise RuntimeError(
            f"{_CONFIG_FILE_OVERRIDE_ENV} must be a full absolute path; '~' is not allowed."
        )
    path = Path(raw)
    if not path.is_absolute():
        raise RuntimeError(
            f"{_CONFIG_FILE_OVERRIDE_ENV} must be a full absolute path: {raw}"
        )
    return path.resolve()


@lru_cache()
def _read_pyproject_dependency_spec(package_name: str) -> str:
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
        except (InvalidRequirement, TypeError):
            continue
        if requirement.name == package_name:
            return str(requirement.specifier)

    raise RuntimeError(f"Dependency {package_name!r} is not declared in pyproject.toml")


def expected_conda_env_name() -> str:
    return f"{DEFAULT_BLOOM_CONDA_ENV_BASE}-{_resolve_deployment_code()}"


def _user_config_dir() -> Path:
    override = _explicit_config_file_override()
    if override is not None:
        return override.parent
    xdg_config_home = Path(
        os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    )
    return xdg_config_home / f"bloom-{_resolve_deployment_code()}"


def _user_config_file() -> Path:
    override = _explicit_config_file_override()
    if override is not None:
        return override
    deployment = _resolve_deployment_code()
    return _user_config_dir() / f"bloom-config-{deployment}.yaml"


def _require_explicit_absolute_path(value: str, *, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise RuntimeError(
            f"{field_name} is required and must be passed as a full absolute path."
        )
    if cleaned.startswith("~"):
        raise RuntimeError(
            f"{field_name} must be a full absolute path; '~' is not allowed."
        )
    if not Path(cleaned).is_absolute():
        raise RuntimeError(f"{field_name} must be a full absolute path. Got: {cleaned}")
    return cleaned


def _default_upload_dir_for_runtime(
    *,
    client_id: str,
    namespace: str,
    env_name: str,
    config_path: str = "",
) -> str:
    _ = client_id
    _ = namespace
    resolved_config_path = _require_explicit_absolute_path(
        config_path,
        field_name="tapdb.config_path",
    )
    scoped_root = Path(resolved_config_path).expanduser().resolve().parent
    return str(scoped_root / env_name.strip().lower() / "uploads")


def _ensure_directory(path_value: str) -> None:
    resolved = Path(path_value).expanduser()
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.debug("Failed to create directory %s: %s", resolved, exc)


def _validate_optional_https_url(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if not normalized.startswith("https://"):
        raise ValueError(f"{field_name} must use an absolute https:// URL")
    return normalized.rstrip("/")


def _validate_bare_host(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if "://" in normalized:
        raise ValueError(f"{field_name} must be a bare host without a scheme")

    parsed = urlsplit(f"//{normalized}")
    if not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} must be a bare host without a path")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a bare host without credentials or a port"
        ) from exc
    if parsed.username or parsed.password or port is not None:
        raise ValueError(
            f"{field_name} must be a bare host without credentials or a port"
        )
    return normalized


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_template_text() -> str:
    try:
        template_text = (
            importlib_resources.files("bloom_lims")
            .joinpath("etc/bloom-config-template.yaml")
            .read_text(encoding="utf-8")
        )
    except Exception as exc:
        logger.debug("Failed to load packaged template config text: %s", exc)
        return ""

    return template_text.replace(
        "__BLOOM_WEB_PORT__", str(DEFAULT_BLOOM_WEB_PORT)
    ).replace("__BLOOM_TAPDB_LOCAL_PG_PORT__", str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT))


def build_default_config_template() -> bytes:
    """Render the default Bloom config template with per-invocation secrets."""
    template_text = _load_template_text()
    if not template_text:
        return b""

    jwt_secret = secrets.token_urlsafe(64)
    rendered = re.sub(
        r'(?m)^(?P<prefix>\s*jwt_secret:\s*)"".*$',
        lambda match: f'{match.group("prefix")}"{jwt_secret}"',
        template_text,
        count=1,
    )
    if rendered == template_text:
        rendered = template_text.replace(
            'jwt_secret: ""', f'jwt_secret: "{jwt_secret}"', 1
        )
    return rendered.encode("utf-8")


def _load_template_config() -> Dict[str, Any]:
    """Load the packaged template configuration."""
    try:
        import yaml
    except ImportError:
        return {}

    template_text = _load_template_text()
    if not template_text:
        return {}

    try:
        loaded = yaml.safe_load(template_text) or {}
    except Exception as exc:
        logger.debug("Failed to parse packaged template config: %s", exc)
        return {}

    return loaded if isinstance(loaded, dict) else {}


def _rendered_template_config_file() -> Path:
    rendered_path = (
        Path(tempfile.gettempdir())
        / f"bloom-config-template-{_resolve_deployment_code()}.yaml"
    )
    template_text = _load_template_text()
    if template_text:
        try:
            if (
                not rendered_path.exists()
                or rendered_path.read_text(encoding="utf-8") != template_text
            ):
                rendered_path.write_text(template_text, encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to materialize rendered template config: %s", exc)
    return rendered_path


def _stable_deployment_color_hex(name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:8], "big") % 360
    red, green, blue = colorsys.hls_to_rgb(hue / 360.0, 0.46, 0.72)
    return "#{:02x}{:02x}{:02x}".format(
        round(red * 255),
        round(green * 255),
        round(blue * 255),
    )


def _stable_region_color_hex(name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    hue = (int.from_bytes(digest[:8], "big") % 360 + 180) % 360
    red, green, blue = colorsys.hls_to_rgb(hue / 360.0, 0.62, 0.45)
    return "#{:02x}{:02x}{:02x}".format(
        round(red * 255),
        round(green * 255),
        round(blue * 255),
    )


def _is_sensitive_config_path(path: str) -> bool:
    normalized = str(path or "").strip().lower()
    return any(token in normalized for token in SENSITIVE_CONFIG_KEYWORDS)


def _sanitize_config_structure(path: str, value: Any) -> Any:
    if _is_sensitive_config_path(path):
        if value in (None, "", [], {}, ()):
            return CONFIG_UNSET
        return CONFIG_REDACTED

    if isinstance(value, dict):
        return {
            str(key): _sanitize_config_structure(
                f"{path}.{key}" if path else str(key),
                item,
            )
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _sanitize_config_structure(f"{path}[{index}]", item)
            for index, item in enumerate(value)
        ]

    if value in (None, ""):
        return CONFIG_UNSET

    return value


def _flatten_config_rows(value: Any, *, prefix: str = "") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key in sorted(value):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_config_rows(value[key], prefix=child_prefix))
        return rows

    if isinstance(value, list):
        rendered = json.dumps(value, sort_keys=True)
    elif isinstance(value, bool):
        rendered = "true" if value else "false"
    elif value == CONFIG_UNSET:
        rendered = CONFIG_UNSET
    else:
        rendered = str(value)

    rows.append({"key": prefix, "value": rendered})
    return rows


def _resolve_deployment_chrome(
    *,
    name: str | None,
    color: str | None,
    fallback_name: str | None = None,
) -> dict[str, str | bool]:
    resolved_name = str(name or "").strip() or str(fallback_name or "").strip()
    resolved_color = str(color or "").strip()
    if not resolved_color:
        resolved_color = (
            _stable_deployment_color_hex(resolved_name)
            if resolved_name
            else DEFAULT_DEPLOYMENT_BANNER_COLOR
        )
    return {
        "name": resolved_name,
        "color": resolved_color,
        "is_production": resolved_name.lower() in PRODUCTION_DEPLOYMENT_NAMES,
    }


def _load_yaml_config() -> Dict[str, Any]:
    """Load and merge template + user YAML config files."""
    try:
        import yaml
    except ImportError:
        return {}

    config: Dict[str, Any] = {}

    template_config = _load_template_config()
    if template_config:
        config = template_config

    _ensure_user_config_dir()

    user_config_file = _user_config_file()
    if user_config_file.exists():
        try:
            with open(user_config_file, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
                config = _deep_merge(config, user_config)
        except Exception as exc:
            logger.debug(
                "Failed to load user config %s: %s",
                user_config_file,
                exc,
            )

    return config


def _ensure_user_config_dir() -> None:
    """Ensure the user config directory exists when the process can create it."""
    user_config_dir = _user_config_dir()
    if user_config_dir.exists():
        return

    try:
        user_config_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.debug(
            "Failed to create user config directory %s: %s",
            user_config_dir,
            exc,
        )


def _yaml_config_files() -> list[Path]:
    _ensure_user_config_dir()
    return [_rendered_template_config_file(), _user_config_file()]


class TapDBSettings(BaseModel):
    """TapDB runtime targeting configuration."""

    env: str = Field(
        default="dev", description="TapDB target environment: dev/test/prod"
    )
    client_id: str = Field(
        default="bloom",
        description="TapDB client namespace key for Bloom runtime config",
    )
    database_name: str = Field(
        default="bloom",
        description="TapDB database namespace key for Bloom runtime config",
    )
    owner_repo_name: str = Field(
        default=DEFAULT_TAPDB_OWNER_REPO_NAME,
        description="TapDB owner repo name for Meridian governance",
    )
    domain_code: str = Field(
        default=DEFAULT_TAPDB_DOMAIN_CODE,
        description="Meridian domain code for TapDB runtime config",
    )
    domain_registry_path: str = Field(
        default="",
        description="Shared Meridian domain registry path",
    )
    prefix_ownership_registry_path: str = Field(
        default="",
        description="Shared Meridian prefix ownership registry path",
    )
    strict_namespace: bool = Field(
        default=True,
        description="Enable strict namespace mode for namespaced TapDB config",
    )
    config_path: str = Field(
        default="",
        description="Required explicit absolute TapDB config path",
    )
    local_pg_port: int = Field(
        default=DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT,
        description="Default local PostgreSQL port for TapDB dev/test runtime",
    )

    @field_validator("env")
    @classmethod
    def validate_env(cls, value: str) -> str:
        env = value.strip().lower()
        if env not in {"dev", "test", "prod"}:
            raise ValueError("tapdb.env must be one of: dev, test, prod")
        return env

    @field_validator("client_id")
    @classmethod
    def validate_client_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("tapdb.client_id cannot be empty")
        return cleaned

    @field_validator("database_name")
    @classmethod
    def validate_database_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("tapdb.database_name cannot be empty")
        return cleaned

    @field_validator("owner_repo_name")
    @classmethod
    def validate_owner_repo_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("tapdb.owner_repo_name cannot be empty")
        return cleaned

    @field_validator("domain_code")
    @classmethod
    def validate_domain_code(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("tapdb.domain_code cannot be empty")
        return cleaned

    @field_validator("domain_registry_path", "prefix_ownership_registry_path")
    @classmethod
    def validate_registry_path(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            return ""
        if cleaned.startswith("~") or not Path(cleaned).is_absolute():
            raise ValueError("tapdb registry paths must be full absolute paths")
        return cleaned

    @field_validator("config_path")
    @classmethod
    def validate_config_path(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            return ""
        if cleaned.startswith("~") or not Path(cleaned).is_absolute():
            raise ValueError("tapdb.config_path must be a full absolute path")
        return cleaned

    @field_validator("local_pg_port")
    @classmethod
    def validate_local_pg_port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError("tapdb.local_pg_port must be between 1 and 65535")
        return value


class TapDBRuntimeContext(BaseModel):
    """Resolved runtime context to pass to daylily-tapdb."""

    env: str
    client_id: str
    database_name: str
    owner_repo_name: str = DEFAULT_TAPDB_OWNER_REPO_NAME
    domain_code: str = DEFAULT_TAPDB_DOMAIN_CODE
    domain_registry_path: str = ""
    prefix_ownership_registry_path: str = ""
    strict_namespace: bool = True
    config_path: str = ""
    aws_profile: str = "lsmc"
    aws_region: str = "us-west-2"


class StorageSettings(BaseModel):
    """File storage configuration."""

    upload_dir: str = Field(default="", description="Upload directory")
    temp_dir: str = Field(
        default_factory=lambda: str(Path(tempfile.gettempdir()) / "bloom"),
        description="Temporary file directory",
    )
    max_file_size_mb: int = Field(default=100, description="Max upload file size (MB)")
    allowed_extensions: List[str] = Field(
        default=["pdf", "csv", "xlsx", "txt", "json", "png", "jpg", "jpeg"],
        description="Allowed file extensions",
    )

    s3_bucket: str = Field(default="", description="S3 bucket name")
    s3_prefix: str = Field(default="bloom-files/", description="S3 key prefix")
    s3_region: str = Field(default="us-east-1", description="S3 region")
    s3_endpoint: str = Field(default="", description="S3-compatible endpoint URL")

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


def _get_default_api_version() -> str:
    try:
        from bloom_lims._version import get_version

        return get_version()
    except ImportError:
        return "0.10.7"


class APISettings(BaseModel):
    """API configuration."""

    title: str = Field(default="BLOOM LIMS API", description="API title")
    version: str = Field(
        default_factory=_get_default_api_version, description="API version"
    )
    prefix: str = Field(default="/api/v1", description="API URL prefix")

    pagination_default_size: int = Field(default=50, description="Default page size")
    pagination_max_size: int = Field(default=1000, description="Maximum page size")

    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_requests: int = Field(default=100, description="Requests per window")
    rate_limit_window_seconds: int = Field(default=60, description="Rate limit window")

    request_timeout_seconds: int = Field(default=30, description="Request timeout")
    long_running_timeout_seconds: int = Field(
        default=300, description="Long-running op timeout"
    )

    cors_origins: List[str] = Field(
        default_factory=lambda: [
            f"https://{item}" for item in APPROVED_WEB_DOMAIN_SUFFIXES
        ],
        description="Allowed CORS origins",
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials")


class AWSSettings(BaseModel):
    """AWS configuration."""

    profile: str = Field(default="lsmc", description="AWS profile name")
    region: str = Field(default="us-west-2", description="Default AWS region")


class NetworkSettings(BaseModel):
    """Inbound host allowlist extensions."""

    allowed_hosts: List[str] = Field(
        default_factory=list,
        description="Additional hostnames or IPs trusted by middleware",
    )


class UISettings(BaseModel):
    """UI metadata configuration."""

    support_email: str = Field(
        default="support@dyly.bio",
        description="Support contact email shown in the GUI footer/help page",
    )
    github_repo_url: str = Field(
        default="https://github.com/Daylily-Informatics/bloom",
        description="Repository URL shown in the GUI footer/help page",
    )
    show_environment_chrome: bool = Field(
        default=True,
        description="Show deployment and region chrome in GUI shells",
    )


class DeploymentSettings(BaseModel):
    """Deployment-specific GUI chrome."""

    name: str = Field(default="", description="Deployment label")
    color: str = Field(default="", description="Deployment banner color")
    is_production: bool = Field(
        default=False, description="Hide deployment banner in production"
    )

    @model_validator(mode="after")
    def normalize_banner(self) -> "DeploymentSettings":
        deployment = _resolve_deployment_chrome(
            name=self.name,
            color=self.color,
            fallback_name=_resolve_deployment_code(),
        )
        self.name = str(deployment["name"])
        self.color = str(deployment["color"])
        self.is_production = bool(deployment["is_production"])
        return self


class AuthSettings(BaseModel):
    """Authentication configuration."""

    cognito_user_pool_id: str = Field(default="", description="Cognito user pool ID")
    cognito_client_id: str = Field(default="", description="Cognito app client ID")
    cognito_client_secret: str = Field(
        default="", description="Cognito app client secret"
    )
    cognito_region: str = Field(default="", description="AWS region for Cognito")
    cognito_domain: str = Field(
        default="", description="Cognito hosted UI domain (bare host only)"
    )
    cognito_redirect_uri: str = Field(default="", description="Cognito redirect URI")
    cognito_logout_redirect_uri: str = Field(
        default="", description="Cognito logout redirect URI"
    )
    cognito_scopes: List[str] = Field(
        default_factory=lambda: ["openid", "email", "profile"],
        description="Cognito OAuth scopes",
    )
    cognito_allowed_domains: List[str] = Field(
        default_factory=lambda: [
            "lsmc.com",
            "lsmc.bio",
            "lsmc.life",
            "daylilyinformatics.com",
        ],
        description="Allowed email domains",
    )
    cognito_default_tenant_id: str = Field(
        default="00000000-0000-0000-0000-000000000000",
        description="Default tenant UUID for auto-provisioned Cognito users",
    )
    auto_provision_allowed_domains: List[str] = Field(
        default_factory=lambda: ["lsmc.com"],
        description="Email domains allowed to auto-provision missing users",
    )

    jwt_secret: str = Field(default="", description="JWT secret key")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiry_hours: int = Field(default=24, description="JWT token expiry (hours)")

    session_timeout_minutes: int = Field(default=30, description="Session timeout")
    max_sessions_per_user: int = Field(default=5, description="Max concurrent sessions")

    @field_validator("cognito_domain")
    @classmethod
    def validate_cognito_domain(cls, value: str) -> str:
        return _validate_bare_host(value, field_name="auth.cognito_domain")


class AtlasSettings(BaseModel):
    """Atlas integration settings."""

    base_url: str = Field(default="", description="Atlas API base URL")
    token: str = Field(default="", description="Atlas API bearer token")
    timeout_seconds: int = Field(default=10, description="Atlas API timeout seconds")
    cache_ttl_seconds: int = Field(
        default=300, description="Atlas response cache TTL in seconds"
    )
    verify_ssl: bool = Field(default=True, description="Verify Atlas TLS certificates")
    organization_id: str = Field(
        default="",
        description="Atlas organization/tenant UUID used for outbound Bloom events",
    )
    events_enabled: bool = Field(
        default=False,
        description="Enable outbound Bloom->Atlas webhook event delivery",
    )
    events_path: str = Field(
        default="/api/integrations/bloom/v1/events",
        description="Atlas webhook path for Bloom events",
    )
    webhook_secret: str = Field(
        default="",
        description="Shared HMAC secret for Bloom webhook signatures",
    )
    events_timeout_seconds: int = Field(
        default=10,
        description="Timeout (seconds) for outbound Bloom webhook delivery",
    )
    events_max_retries: int = Field(
        default=2,
        description="Maximum retry count for outbound Bloom webhook delivery",
    )
    status_events_timeout_seconds: int = Field(
        default=10,
        description="Timeout (seconds) for Bloom -> Atlas test-order status event calls",
    )
    status_events_max_retries: int = Field(
        default=5,
        description="Maximum retry count for Bloom -> Atlas status event calls",
    )
    status_events_backoff_base_seconds: float = Field(
        default=0.5,
        description="Base backoff delay in seconds for Bloom -> Atlas status event retries",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _validate_optional_https_url(value, field_name="atlas.base_url")


class DeweySettings(BaseModel):
    """Dewey integration settings."""

    enabled: bool = Field(
        default=False, description="Enable Bloom -> Dewey artifact registration"
    )
    base_url: str = Field(default="", description="Dewey API base URL")
    token: str = Field(default="", description="Dewey API bearer token")
    timeout_seconds: int = Field(default=10, description="Dewey API timeout seconds")
    verify_ssl: bool = Field(default=True, description="Verify Dewey TLS certificates")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _validate_optional_https_url(value, field_name="dewey.base_url")

    @model_validator(mode="after")
    def validate_enabled_contract(self) -> "DeweySettings":
        if self.enabled:
            if not str(self.base_url or "").strip():
                raise ValueError("dewey.base_url is required when dewey.enabled=true")
            if not str(self.token or "").strip():
                raise ValueError("dewey.token is required when dewey.enabled=true")
        return self


class ZebraDaySettings(BaseModel):
    """zebra_day integration settings."""

    base_url: str = Field(default="", description="zebra_day API base URL")
    token: str = Field(default="", description="zebra_day internal API bearer token")
    timeout_seconds: int = Field(
        default=10, description="zebra_day API timeout seconds"
    )
    verify_ssl: bool = Field(
        default=True, description="Verify zebra_day TLS certificates"
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        if not normalized.startswith(("https://", "http://")):
            raise ValueError(
                "zebra_day.base_url must use an absolute http:// or https:// URL"
            )
        return normalized.rstrip("/")


class LoggingSettings(BaseModel):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Log level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format",
    )
    json_format: bool = Field(default=False, description="Use JSON log format")
    log_file: str = Field(default="", description="Log file path (empty for stdout)")
    max_file_size_mb: int = Field(default=10, description="Max log file size")
    backup_count: int = Field(default=5, description="Number of backup files")


class FeatureFlags(BaseModel):
    """Feature flags for enabling/disabling features."""

    enable_audit_logging: bool = Field(default=True, description="Enable audit trail")
    enable_workflow_notifications: bool = Field(
        default=True, description="Workflow notifications"
    )
    enable_file_versioning: bool = Field(
        default=True, description="Enable file versioning"
    )
    enable_advanced_search: bool = Field(
        default=True, description="Advanced search features"
    )
    enable_api_caching: bool = Field(
        default=False, description="Enable API response caching"
    )
    maintenance_mode: bool = Field(default=False, description="Enable maintenance mode")


class CacheSettings(BaseModel):
    """Cache configuration for application caching layer."""

    enabled: bool = Field(default=True, description="Enable caching")
    backend: str = Field(
        default="memory", description="Cache backend: memory, redis, memcached"
    )
    max_size: int = Field(default=5000, description="Maximum cache entries")
    default_ttl: int = Field(default=300, description="Default TTL in seconds")

    template_ttl: int = Field(default=3600, description="Template cache TTL")
    instance_ttl: int = Field(default=300, description="Instance cache TTL")
    lineage_ttl: int = Field(default=300, description="Lineage cache TTL")
    query_ttl: int = Field(default=60, description="Query result cache TTL")

    template_prefix: str = Field(
        default="tmpl:", description="Template cache key prefix"
    )
    instance_prefix: str = Field(
        default="inst:", description="Instance cache key prefix"
    )
    query_prefix: str = Field(default="qry:", description="Query cache key prefix")

    redis_host: str = Field(default="localhost", description="Redis server host")
    redis_port: int = Field(default=6379, description="Redis server port")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_password: Optional[str] = Field(default=None, description="Redis password")
    redis_ssl: bool = Field(default=False, description="Enable Redis SSL/TLS")
    redis_cluster: bool = Field(default=False, description="Enable Redis Cluster mode")

    memcached_servers: List[str] = Field(
        default=["localhost:11211"],
        description="Memcached server addresses",
    )


class BusinessConstants(BaseModel):
    """Business logic constants extracted from code."""

    default_version: str = Field(default="1.0", description="Default object version")
    wildcard_version: str = Field(default="*", description="Wildcard version string")

    status_created: str = Field(default="created", description="Created status")
    status_in_progress: str = Field(
        default="in_progress", description="In progress status"
    )
    status_complete: str = Field(default="complete", description="Complete status")
    status_failed: str = Field(default="failed", description="Failed status")
    status_abandoned: str = Field(default="abandoned", description="Abandoned status")
    status_active: str = Field(default="active", description="Active status")

    workflow_state_active: str = Field(
        default="active", description="Active workflow state"
    )
    workflow_state_paused: str = Field(
        default="paused", description="Paused workflow state"
    )
    workflow_state_completed: str = Field(
        default="completed", description="Completed workflow state"
    )

    template_suffix: str = Field(
        default="_template", description="Template table suffix"
    )
    instance_suffix: str = Field(
        default="_instance", description="Instance table suffix"
    )
    lineage_suffix: str = Field(
        default="_instance_lineage", description="Lineage table suffix"
    )

    singleton_true_values: List[str] = Field(
        default=["1", "true", "True", "yes", "Yes"],
        description="Values that indicate singleton=True",
    )
    singleton_false_values: List[str] = Field(
        default=["0", "false", "False", "no", "No", ""],
        description="Values that indicate singleton=False",
    )

    max_lineage_depth: int = Field(
        default=10, description="Max depth for lineage queries"
    )
    max_children_per_query: int = Field(
        default=10000, description="Max children in recursive queries"
    )

    default_label_style: str = Field(
        default="tube_2inX1in", description="Default label style"
    )
    default_lab_code: str = Field(default="BLOOM", description="Default lab code")

    default_timezone: str = Field(default="UTC", description="Default timezone")

    config_base_path: str = Field(
        default="config", description="Base path for template configurations"
    )

    action_max_executions_unlimited: str = Field(
        default="-1", description="Unlimited action executions"
    )
    action_enabled_true: str = Field(default="1", description="Action enabled value")
    action_enabled_false: str = Field(default="0", description="Action disabled value")


class BloomSettings(BaseSettings):
    """Main settings class for BLOOM LIMS."""

    model_config = SettingsConfigDict(
        env_prefix="BLOOM_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="BLOOM LIMS", description="Application name")
    environment: str = Field(default="development", description="Environment name")
    debug: bool = Field(default=False, description="Debug mode")

    tapdb: TapDBSettings = Field(default_factory=TapDBSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    api: APISettings = Field(default_factory=APISettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    atlas: AtlasSettings = Field(default_factory=AtlasSettings)
    dewey: DeweySettings = Field(default_factory=DeweySettings)
    zebra_day: ZebraDaySettings = Field(default_factory=ZebraDaySettings)
    aws: AWSSettings = Field(default_factory=AWSSettings)
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    ui: UISettings = Field(default_factory=UISettings)
    deployment: DeploymentSettings = Field(default_factory=DeploymentSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    constants: BusinessConstants = Field(default_factory=BusinessConstants)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        _ = dotenv_settings
        return (
            init_settings,
            env_settings,
            file_secret_settings,
            YamlConfigSettingsSource(
                settings_cls,
                yaml_file=_yaml_config_files(),
                yaml_file_encoding="utf-8",
            ),
        )

    @model_validator(mode="after")
    def validate_dewey_settings(self) -> "BloomSettings":
        if self.dewey.enabled:
            if not str(self.dewey.base_url or "").strip():
                raise ValueError("dewey.base_url is required when dewey.enabled=true")
            if not str(self.dewey.token or "").strip():
                raise ValueError("dewey.token is required when dewey.enabled=true")
        return self

    @model_validator(mode="after")
    def normalize_local_storage_paths(self) -> "BloomSettings":
        configured_upload_dir = str(self.storage.upload_dir or "").strip()
        if (
            not configured_upload_dir or configured_upload_dir == LEGACY_UPLOAD_DIR
        ) and str(self.tapdb.config_path or "").strip():
            self.storage.upload_dir = _default_upload_dir_for_runtime(
                client_id=self.tapdb.client_id.strip(),
                namespace=self.tapdb.database_name.strip(),
                env_name=self.tapdb.env.strip().lower(),
                config_path=self.tapdb.config_path,
            )

        if str(self.storage.upload_dir or "").strip():
            _ensure_directory(self.storage.upload_dir)
        return self

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        env = value.lower()
        valid_envs = ["development", "staging", "production", "testing"]
        if env not in valid_envs:
            raise ValueError(f"Environment must be one of: {', '.join(valid_envs)}")
        return env

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    # Compatibility aliases for explicit tapdb context naming.
    @property
    def tapdb_env(self) -> str:
        return self.tapdb.env

    @property
    def tapdb_database_name(self) -> str:
        return self.tapdb.database_name

    @property
    def tapdb_config_path(self) -> str:
        return self.tapdb.config_path


@lru_cache()
def get_settings() -> BloomSettings:
    return BloomSettings()


def get_tapdb_runtime_context(
    settings: Optional[BloomSettings] = None,
) -> TapDBRuntimeContext:
    """Resolve active TapDB runtime context from Bloom config."""
    settings = settings or get_settings()
    config_path = _require_explicit_absolute_path(
        settings.tapdb.config_path,
        field_name="tapdb.config_path",
    )
    domain_registry_path = _require_explicit_absolute_path(
        settings.tapdb.domain_registry_path,
        field_name="tapdb.domain_registry_path",
    )
    prefix_ownership_registry_path = _require_explicit_absolute_path(
        settings.tapdb.prefix_ownership_registry_path,
        field_name="tapdb.prefix_ownership_registry_path",
    )
    return TapDBRuntimeContext(
        env=settings.tapdb.env.strip().lower(),
        client_id=settings.tapdb.client_id.strip(),
        database_name=settings.tapdb.database_name.strip(),
        owner_repo_name=settings.tapdb.owner_repo_name.strip(),
        domain_code=settings.tapdb.domain_code.strip().upper(),
        domain_registry_path=domain_registry_path,
        prefix_ownership_registry_path=prefix_ownership_registry_path,
        strict_namespace=settings.tapdb.strict_namespace,
        config_path=config_path,
        aws_profile=(settings.aws.profile or "lsmc").strip(),
        aws_region=(settings.aws.region or "us-west-2").strip(),
    )


def apply_runtime_environment(
    settings: Optional[BloomSettings] = None,
) -> TapDBRuntimeContext:
    """Return normalized Bloom runtime context without mutating TAPDB env."""
    settings = settings or get_settings()
    ctx = get_tapdb_runtime_context(settings=settings)
    return ctx


def get_tapdb_db_config(
    env_name: Optional[str] = None,
    database_name: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict[str, str]:
    """Resolve active DB config via daylily-tapdb config loader."""
    settings = get_settings()
    ctx = apply_runtime_environment(settings)

    target_env = (env_name or ctx.env).strip().lower()

    from daylily_tapdb.cli.db_config import get_db_config_for_env

    return get_db_config_for_env(
        target_env,
        config_path=(config_path or ctx.config_path or None),
        client_id=ctx.client_id,
        database_name=(database_name or ctx.database_name),
    )


def assert_tapdb_version() -> str:
    """Assert installed daylily-tapdb version matches the Bloom pin."""
    pinned_spec = _read_pyproject_dependency_spec("daylily-tapdb")

    try:
        installed = Version(importlib.metadata.version("daylily-tapdb"))
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("daylily-tapdb is not installed") from exc

    if pinned_spec:
        from packaging.specifiers import SpecifierSet

        if installed not in SpecifierSet(pinned_spec):
            raise RuntimeError(
                f"Unsupported daylily-tapdb version {installed}; expected {pinned_spec}"
            )

    return str(installed)


def generate_example_webhook_secret(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def atlas_webhook_secret_warning(
    settings: "BloomSettings | None" = None,
    *,
    suggested_secret: str | None = None,
) -> str | None:
    active_settings = settings or get_settings()
    if str(active_settings.atlas.webhook_secret or "").strip():
        return None
    example = suggested_secret or generate_example_webhook_secret()
    return (
        "Atlas webhook signature secret is not configured "
        "(atlas.webhook_secret is empty). Bloom can still start, but signed Atlas webhook "
        "delivery and verification will not be safe or interoperable. Set a 20-character "
        f"alphanumeric secret such as: {example}"
    )


def validate_settings() -> List[str]:
    """Validate settings and return list of warnings/issues."""
    warnings: List[str] = []
    settings = get_settings()

    try:
        assert_tapdb_version()
    except Exception as exc:
        warnings.append(f"TapDB version check failed: {exc}")

    if not settings.auth.cognito_user_pool_id:
        warnings.append(
            "Cognito configuration is missing (auth.cognito_user_pool_id). "
            f"Set it in the deployment YAML config: {get_user_config_path()}"
        )

    if not settings.auth.jwt_secret and settings.is_production:
        warnings.append("JWT secret is not set in production")

    upload_dir = str(settings.storage.upload_dir or "").strip()
    if upload_dir:
        upload_path = Path(upload_dir).expanduser()
        if not upload_path.exists():
            warnings.append(
                f"Upload directory does not exist: {settings.storage.upload_dir}"
            )
        elif not upload_path.is_dir():
            warnings.append(
                f"Upload path is not a directory: {settings.storage.upload_dir}"
            )
        elif not os.access(upload_path, os.W_OK):
            warnings.append(
                f"Upload directory is not writable: {settings.storage.upload_dir}"
            )

    if settings.storage.s3_bucket and not os.environ.get("AWS_ACCESS_KEY_ID"):
        warnings.append("S3 bucket configured but AWS_ACCESS_KEY_ID not set")

    atlas_secret_warning = atlas_webhook_secret_warning(settings)
    if atlas_secret_warning:
        warnings.append(atlas_secret_warning)

    return warnings


def validate_config_content(content: str) -> List[str]:
    """Validate YAML config content without consulting runtime environment."""
    try:
        import yaml
    except ImportError:
        return ["PyYAML is required to validate configuration"]

    try:
        parsed = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        return [f"YAML parse error: {exc}"]

    if not isinstance(parsed, dict):
        return ["Root YAML object must be a mapping"]

    merged = _deep_merge(_load_template_config(), parsed)

    try:
        BloomSettings.model_validate(merged)
    except Exception as exc:
        details = getattr(exc, "errors", None)
        if callable(details):
            messages: List[str] = []
            for item in details():
                location = ".".join(str(part) for part in item.get("loc", ()))
                message = item.get("msg", str(exc))
                if location:
                    messages.append(f"{location}: {message}")
                else:
                    messages.append(message)
            if messages:
                return messages
        return [str(exc)]

    return []


# Legacy compatibility
def get_database_url() -> str:
    """Build runtime database URL from TapDB resolved configuration."""
    cfg = get_tapdb_db_config()
    auth = cfg["user"]
    if cfg.get("password"):
        auth = f"{cfg['user']}:{cfg['password']}"

    url = f"postgresql://{auth}@{cfg['host']}:{cfg['port']}/{cfg['database']}"
    if cfg.get("engine_type") == "aurora":
        return f"{url}?sslmode=verify-full"
    return url


def get_cognito_config() -> tuple[str, str, str]:
    settings = get_settings()
    return (
        settings.auth.cognito_region,
        settings.auth.cognito_user_pool_id,
        settings.auth.cognito_client_id,
    )


def get_user_config_path() -> Path:
    return _user_config_file()


def get_template_config_path() -> Path:
    return TEMPLATE_CONFIG_FILE


def build_effective_config_summary(
    settings: Optional["BloomSettings"] = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    dumped = active_settings.model_dump(mode="python")
    sanitized = _sanitize_config_structure("", dumped)
    rows = _flatten_config_rows(sanitized)
    return {
        "user_config_path": str(get_user_config_path()),
        "template_config_path": str(get_template_config_path()),
        "tapdb_config_path": str(active_settings.tapdb.config_path),
        "tapdb_owner_repo_name": str(active_settings.tapdb.owner_repo_name),
        "tapdb_domain_code": str(active_settings.tapdb.domain_code),
        "tapdb_domain_registry_path": str(active_settings.tapdb.domain_registry_path),
        "tapdb_prefix_ownership_registry_path": str(
            active_settings.tapdb.prefix_ownership_registry_path
        ),
        "deployment_name": str(
            active_settings.deployment.name or _resolve_deployment_code()
        ),
        "aws_region": str(active_settings.aws.region or "us-west-2"),
        "build_version": _get_default_api_version(),
        "show_environment_chrome": bool(active_settings.ui.show_environment_chrome),
        "effective_rows": rows,
    }


def ensure_user_config_exists() -> Path:
    """Ensure user config directory and file exist."""
    user_config_dir = _user_config_dir()
    user_config_file = _user_config_file()
    if not user_config_dir.exists():
        user_config_dir.mkdir(parents=True, exist_ok=True)

    if not user_config_file.exists():
        template_text = _load_template_text()
        if template_text:
            user_config_file.write_text(template_text, encoding="utf-8")

    return user_config_file
