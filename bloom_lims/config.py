"""
BLOOM LIMS Configuration Management.

Configuration precedence (highest to lowest):
1. Environment variables (BLOOM_* prefix and TAPDB_* runtime context)
2. User config file (~/.config/bloom/config.yaml)
3. Template defaults
"""

import importlib.metadata
import logging
import os
import tempfile
from functools import lru_cache
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any, Dict, List, Optional

from packaging.version import Version
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import (
    PydanticBaseSettingsSource,
    YamlConfigSettingsSource,
)

from bloom_lims.domain_access import APPROVED_WEB_DOMAIN_SUFFIXES

logger = logging.getLogger(__name__)

# Config file paths
USER_CONFIG_DIR = Path.home() / ".config" / "bloom"
USER_CONFIG_FILE = USER_CONFIG_DIR / "config.yaml"
TEMPLATE_CONFIG_FILE = Path(__file__).resolve().parent / "etc" / "bloom-config-template.yaml"


def _validate_optional_https_url(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if not normalized.startswith("https://"):
        raise ValueError(f"{field_name} must use an absolute https:// URL")
    return normalized.rstrip("/")


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_template_config() -> Dict[str, Any]:
    """Load the packaged template configuration."""
    try:
        import yaml
    except ImportError:
        return {}

    try:
        template_text = (
            importlib_resources.files("bloom_lims")
            .joinpath("etc/bloom-config-template.yaml")
            .read_text(encoding="utf-8")
        )
    except Exception as exc:
        logger.debug("Failed to load packaged template config: %s", exc)
        return {}

    try:
        loaded = yaml.safe_load(template_text) or {}
    except Exception as exc:
        logger.debug("Failed to parse packaged template config: %s", exc)
        return {}

    return loaded if isinstance(loaded, dict) else {}


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

    if USER_CONFIG_FILE.exists():
        try:
            with open(USER_CONFIG_FILE, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
                config = _deep_merge(config, user_config)
        except Exception as exc:
            logger.debug(
                "Failed to load user config %s: %s",
                USER_CONFIG_FILE,
                exc,
            )

    return config


def _ensure_user_config_dir() -> None:
    """Ensure the user config directory exists when the process can create it."""
    if USER_CONFIG_DIR.exists():
        return

    try:
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.debug(
            "Failed to create user config directory %s: %s",
            USER_CONFIG_DIR,
            exc,
        )


def _yaml_config_files() -> list[Path]:
    _ensure_user_config_dir()
    return [TEMPLATE_CONFIG_FILE, USER_CONFIG_FILE]


class TapDBSettings(BaseModel):
    """TapDB runtime targeting configuration."""

    env: str = Field(
        default="dev", description="TapDB target environment: dev/test/prod"
    )
    client_id: str = Field(
        default="bloom",
        description="TapDB client namespace key (TAPDB_CLIENT_ID)",
    )
    database_name: str = Field(
        default="bloom",
        description="TapDB database namespace key (TAPDB_DATABASE_NAME)",
    )
    strict_namespace: bool = Field(
        default=True,
        description="Enable strict namespace mode (TAPDB_STRICT_NAMESPACE=1 requires v2 namespaced config)",
    )
    config_path: str = Field(
        default="",
        description="Optional explicit TAPDB_CONFIG_PATH override",
    )
    local_pg_port: int = Field(
        default=5566,
        description="Default local PostgreSQL port for TapDB dev/test runtime",
    )
    min_version: str = Field(
        default="3.0.2", description="Minimum supported daylily-tapdb"
    )
    max_version_exclusive: str = Field(
        default="4.0.0",
        description="Exclusive upper bound for daylily-tapdb",
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
    strict_namespace: bool = True
    config_path: str = ""
    aws_profile: str = "lsmc"
    aws_region: str = "us-west-2"


class StorageSettings(BaseModel):
    """File storage configuration."""

    upload_dir: str = Field(
        default="/var/lib/bloom/uploads", description="Upload directory"
    )
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
        default_factory=lambda: [f"https://{item}" for item in APPROVED_WEB_DOMAIN_SUFFIXES],
        description="Allowed CORS origins",
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials")


class AWSSettings(BaseModel):
    """AWS configuration."""

    profile: str = Field(default="lsmc", description="AWS profile name")
    region: str = Field(default="us-west-2", description="Default AWS region")


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


class DeploymentSettings(BaseModel):
    """Deployment-specific GUI chrome."""

    name: str = Field(default="", description="Deployment label")
    color: str = Field(default="#0f766e", description="Deployment banner color")
    is_production: bool = Field(default=False, description="Hide deployment banner in production")


class AuthSettings(BaseModel):
    """Authentication configuration."""

    cognito_user_pool_id: str = Field(default="", description="Cognito user pool ID")
    cognito_client_id: str = Field(default="", description="Cognito app client ID")
    cognito_client_secret: str = Field(
        default="", description="Cognito app client secret"
    )
    cognito_region: str = Field(default="", description="AWS region for Cognito")
    cognito_domain: str = Field(default="", description="Cognito hosted UI domain")
    cognito_redirect_uri: str = Field(default="", description="Cognito redirect URI")
    cognito_logout_redirect_uri: str = Field(
        default="", description="Cognito logout redirect URI"
    )
    cognito_scopes: List[str] = Field(
        default_factory=lambda: ["openid", "email", "profile"],
        description="Cognito OAuth scopes",
    )
    cognito_allowed_domains: List[str] = Field(
        default_factory=lambda: list(APPROVED_WEB_DOMAIN_SUFFIXES),
        description="Allowed email domains",
    )

    jwt_secret: str = Field(default="", description="JWT secret key")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiry_hours: int = Field(default=24, description="JWT token expiry (hours)")

    session_timeout_minutes: int = Field(default=30, description="Session timeout")
    max_sessions_per_user: int = Field(default=5, description="Max concurrent sessions")


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

    enabled: bool = Field(default=False, description="Enable Bloom -> Dewey artifact registration")
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
    aws: AWSSettings = Field(default_factory=AWSSettings)
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
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(
                settings_cls,
                yaml_file=_yaml_config_files(),
                yaml_file_encoding="utf-8",
                deep_merge=True,
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
    """Resolve active TapDB runtime context from env + config."""
    settings = settings or get_settings()
    raw_strict = os.environ.get("TAPDB_STRICT_NAMESPACE")
    strict_namespace = settings.tapdb.strict_namespace
    if raw_strict is not None and str(raw_strict).strip():
        strict_namespace = str(raw_strict).strip().lower() in {"1", "true", "yes", "on"}
    return TapDBRuntimeContext(
        env=(os.environ.get("TAPDB_ENV") or settings.tapdb.env).strip().lower(),
        client_id=(
            os.environ.get("TAPDB_CLIENT_ID") or settings.tapdb.client_id
        ).strip(),
        database_name=(
            os.environ.get("TAPDB_DATABASE_NAME") or settings.tapdb.database_name
        ).strip(),
        strict_namespace=strict_namespace,
        config_path=(
            os.environ.get("TAPDB_CONFIG_PATH") or settings.tapdb.config_path
        ).strip(),
        aws_profile=(
            os.environ.get("AWS_PROFILE") or settings.aws.profile or "lsmc"
        ).strip(),
        aws_region=(
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or settings.aws.region
            or "us-west-2"
        ).strip(),
    )


def apply_runtime_environment(
    settings: Optional[BloomSettings] = None,
) -> TapDBRuntimeContext:
    """Apply normalized TAPDB/AWS runtime environment variables."""
    settings = settings or get_settings()
    ctx = get_tapdb_runtime_context(settings=settings)

    os.environ.setdefault("TAPDB_ENV", ctx.env)
    os.environ.setdefault("TAPDB_CLIENT_ID", ctx.client_id)
    os.environ.setdefault("TAPDB_DATABASE_NAME", ctx.database_name)
    os.environ.setdefault(
        "TAPDB_STRICT_NAMESPACE", "1" if ctx.strict_namespace else "0"
    )
    if ctx.config_path:
        os.environ.setdefault("TAPDB_CONFIG_PATH", ctx.config_path)

    # Bloom-local TapDB dev/test should default to a non-standard port so it
    # can coexist with other local PostgreSQL services on 5432.
    local_pg_port = str(
        os.environ.get("BLOOM_TAPDB_LOCAL_PG_PORT") or settings.tapdb.local_pg_port
    )
    os.environ.setdefault("BLOOM_TAPDB_LOCAL_PG_PORT", local_pg_port)
    os.environ.setdefault("TAPDB_DEV_PORT", local_pg_port)
    os.environ.setdefault("TAPDB_TEST_PORT", local_pg_port)

    os.environ.setdefault("AWS_PROFILE", ctx.aws_profile)
    os.environ.setdefault("AWS_REGION", ctx.aws_region)
    os.environ.setdefault("AWS_DEFAULT_REGION", ctx.aws_region)

    return ctx


def get_tapdb_db_config(
    env_name: Optional[str] = None,
    database_name: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict[str, str]:
    """Resolve active DB config via daylily-tapdb config loader."""
    settings = get_settings()
    ctx = apply_runtime_environment(settings)

    if database_name:
        os.environ["TAPDB_DATABASE_NAME"] = database_name
    if config_path:
        os.environ["TAPDB_CONFIG_PATH"] = config_path

    target_env = (env_name or ctx.env).strip().lower()

    from daylily_tapdb.cli.db_config import get_db_config_for_env

    return get_db_config_for_env(target_env)


def assert_tapdb_version(
    min_version: Optional[str] = None,
    max_version_exclusive: Optional[str] = None,
) -> str:
    """Assert installed daylily-tapdb version is within the supported range."""
    settings = get_settings()
    min_v = Version(min_version or settings.tapdb.min_version)
    max_v = Version(max_version_exclusive or settings.tapdb.max_version_exclusive)

    try:
        installed = Version(importlib.metadata.version("daylily-tapdb"))
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("daylily-tapdb is not installed") from exc

    if installed < min_v or installed >= max_v:
        raise RuntimeError(
            f"Unsupported daylily-tapdb version {installed}; expected >= {min_v} and < {max_v}"
        )

    return str(installed)


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
            "Set it in YAML config or override it with BLOOM_AUTH__COGNITO_USER_POOL_ID."
        )

    if not settings.auth.jwt_secret and settings.is_production:
        warnings.append("JWT secret is not set in production")

    upload_path = Path(settings.storage.upload_dir)
    if not upload_path.exists():
        warnings.append(
            f"Upload directory does not exist: {settings.storage.upload_dir}"
        )

    if settings.storage.s3_bucket and not os.environ.get("AWS_ACCESS_KEY_ID"):
        warnings.append("S3 bucket configured but AWS_ACCESS_KEY_ID not set")

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
    return USER_CONFIG_FILE


def get_template_config_path() -> Path:
    return TEMPLATE_CONFIG_FILE


def ensure_user_config_exists() -> Path:
    """Ensure user config directory and file exist."""
    import shutil

    if not USER_CONFIG_DIR.exists():
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not USER_CONFIG_FILE.exists() and TEMPLATE_CONFIG_FILE.exists():
        shutil.copy(TEMPLATE_CONFIG_FILE, USER_CONFIG_FILE)

    return USER_CONFIG_FILE
