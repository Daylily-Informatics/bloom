"""
BLOOM LIMS Configuration Management

Centralized configuration using Pydantic Settings with support for environment
variable overrides. All hardcoded values should be defined here.

Usage:
    from bloom_lims.config import get_settings
    
    settings = get_settings()
    print(settings.database.host)
    print(settings.api.pagination_default_size)
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, List, Any
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReadReplicaSettings(BaseModel):
    """Configuration for a single read replica."""

    host: str = Field(description="Replica host address")
    port: int = Field(default=5432, description="Replica port")
    weight: int = Field(default=1, description="Load balancing weight (higher = more traffic)")
    max_lag_seconds: int = Field(default=30, description="Maximum acceptable replication lag")
    enabled: bool = Field(default=True, description="Whether this replica is enabled")


class DatabaseSettings(BaseModel):
    """Database connection configuration."""

    host: str = Field(default="localhost", description="PostgreSQL host")
    port: int = Field(default=5432, description="PostgreSQL port")
    database: str = Field(default="bloom_lims", description="Database name")
    user: str = Field(default="postgres", description="Database user")
    password: str = Field(default="", description="Database password")
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max pool overflow")
    pool_timeout: int = Field(default=30, description="Pool connection timeout (seconds)")
    pool_recycle: int = Field(default=1800, description="Connection recycle time (seconds)")
    echo: bool = Field(default=False, description="Echo SQL statements")

    # Read replica configuration
    read_replicas: List[ReadReplicaSettings] = Field(
        default=[],
        description="List of read replica configurations for scaling reads"
    )
    enable_read_replicas: bool = Field(
        default=False,
        description="Enable read replica routing"
    )
    replica_health_check_interval: int = Field(
        default=30,
        description="Seconds between replica health checks"
    )

    @property
    def connection_string(self) -> str:
        """Generate SQLAlchemy connection string."""
        if self.password:
            return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.database}"

    @property
    def async_connection_string(self) -> str:
        """Generate async SQLAlchemy connection string."""
        if self.password:
            return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        return f"postgresql+asyncpg://{self.user}@{self.host}:{self.port}/{self.database}"


class StorageSettings(BaseModel):
    """File storage configuration."""
    
    # Local storage
    upload_dir: str = Field(default="/var/lib/bloom/uploads", description="Upload directory")
    temp_dir: str = Field(default="/tmp/bloom", description="Temporary file directory")
    max_file_size_mb: int = Field(default=100, description="Max upload file size (MB)")
    allowed_extensions: List[str] = Field(
        default=["pdf", "csv", "xlsx", "txt", "json", "png", "jpg", "jpeg"],
        description="Allowed file extensions"
    )
    
    # S3/Object storage
    s3_bucket: str = Field(default="", description="S3 bucket name")
    s3_prefix: str = Field(default="bloom-files/", description="S3 key prefix")
    s3_region: str = Field(default="us-east-1", description="S3 region")
    s3_endpoint: str = Field(default="", description="S3-compatible endpoint URL")
    
    @property
    def max_file_size_bytes(self) -> int:
        """Get max file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024


def _get_default_api_version() -> str:
    """Get default API version from _version module."""
    try:
        from bloom_lims._version import get_version
        return get_version()
    except ImportError:
        return "0.10.7"


class APISettings(BaseModel):
    """API configuration."""

    title: str = Field(default="BLOOM LIMS API", description="API title")
    version: str = Field(default_factory=_get_default_api_version, description="API version")
    prefix: str = Field(default="/api/v1", description="API URL prefix")
    
    # Pagination
    pagination_default_size: int = Field(default=50, description="Default page size")
    pagination_max_size: int = Field(default=1000, description="Maximum page size")
    
    # Rate limiting
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_requests: int = Field(default=100, description="Requests per window")
    rate_limit_window_seconds: int = Field(default=60, description="Rate limit window")
    
    # Timeouts
    request_timeout_seconds: int = Field(default=30, description="Request timeout")
    long_running_timeout_seconds: int = Field(default=300, description="Long-running op timeout")
    
    # CORS
    cors_origins: List[str] = Field(default=["*"], description="Allowed CORS origins")
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials")


class AuthSettings(BaseModel):
    """Authentication configuration."""
    
    # Cognito
    cognito_user_pool_id: str = Field(default="", description="Cognito user pool ID")
    cognito_client_id: str = Field(default="", description="Cognito app client ID")
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
        default_factory=list, description="Allowed email domains"
    )
    
    # JWT
    jwt_secret: str = Field(default="", description="JWT secret key")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiry_hours: int = Field(default=24, description="JWT token expiry (hours)")
    
    # Session
    session_timeout_minutes: int = Field(default=30, description="Session timeout")
    max_sessions_per_user: int = Field(default=5, description="Max concurrent sessions")


class LoggingSettings(BaseModel):
    """Logging configuration."""
    
    level: str = Field(default="INFO", description="Log level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format"
    )
    json_format: bool = Field(default=False, description="Use JSON log format")
    log_file: str = Field(default="", description="Log file path (empty for stdout)")
    max_file_size_mb: int = Field(default=10, description="Max log file size")
    backup_count: int = Field(default=5, description="Number of backup files")


class FeatureFlags(BaseModel):
    """Feature flags for enabling/disabling features."""

    enable_audit_logging: bool = Field(default=True, description="Enable audit trail")
    enable_workflow_notifications: bool = Field(default=True, description="Workflow notifications")
    enable_file_versioning: bool = Field(default=True, description="Enable file versioning")
    enable_advanced_search: bool = Field(default=True, description="Advanced search features")
    enable_api_caching: bool = Field(default=False, description="Enable API response caching")
    maintenance_mode: bool = Field(default=False, description="Enable maintenance mode")


class CacheSettings(BaseModel):
    """Cache configuration for application caching layer."""

    enabled: bool = Field(default=True, description="Enable caching")
    backend: str = Field(
        default="memory",
        description="Cache backend: 'memory', 'redis', or 'memcached'"
    )
    max_size: int = Field(default=5000, description="Maximum cache entries (memory backend)")
    default_ttl: int = Field(default=300, description="Default TTL in seconds (5 minutes)")

    # TTL settings for different object types (in seconds)
    template_ttl: int = Field(default=3600, description="Template cache TTL (1 hour)")
    instance_ttl: int = Field(default=300, description="Instance cache TTL (5 minutes)")
    lineage_ttl: int = Field(default=300, description="Lineage cache TTL (5 minutes)")
    query_ttl: int = Field(default=60, description="Query result cache TTL (1 minute)")

    # Cache key prefixes
    template_prefix: str = Field(default="tmpl:", description="Template cache key prefix")
    instance_prefix: str = Field(default="inst:", description="Instance cache key prefix")
    query_prefix: str = Field(default="qry:", description="Query cache key prefix")

    # Redis backend configuration
    redis_host: str = Field(default="localhost", description="Redis server host")
    redis_port: int = Field(default=6379, description="Redis server port")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_password: Optional[str] = Field(default=None, description="Redis password")
    redis_ssl: bool = Field(default=False, description="Enable Redis SSL/TLS")
    redis_cluster: bool = Field(default=False, description="Enable Redis Cluster mode")

    # Memcached backend configuration
    memcached_servers: List[str] = Field(
        default=["localhost:11211"],
        description="Memcached server addresses"
    )


class BusinessConstants(BaseModel):
    """Business logic constants extracted from code."""

    # Version defaults
    default_version: str = Field(default="1.0", description="Default object version")
    wildcard_version: str = Field(default="*", description="Wildcard version string")

    # Status values
    status_created: str = Field(default="created", description="Created status")
    status_in_progress: str = Field(default="in_progress", description="In progress status")
    status_complete: str = Field(default="complete", description="Complete status")
    status_failed: str = Field(default="failed", description="Failed status")
    status_abandoned: str = Field(default="abandoned", description="Abandoned status")
    status_active: str = Field(default="active", description="Active status")

    # Workflow states
    workflow_state_active: str = Field(default="active", description="Active workflow state")
    workflow_state_paused: str = Field(default="paused", description="Paused workflow state")
    workflow_state_completed: str = Field(default="completed", description="Completed workflow state")

    # Object type prefixes
    template_suffix: str = Field(default="_template", description="Template table suffix")
    instance_suffix: str = Field(default="_instance", description="Instance table suffix")
    lineage_suffix: str = Field(default="_instance_lineage", description="Lineage table suffix")

    # Singleton handling
    singleton_true_values: List[str] = Field(
        default=["1", "true", "True", "yes", "Yes"],
        description="Values that indicate singleton=True"
    )
    singleton_false_values: List[str] = Field(
        default=["0", "false", "False", "no", "No", ""],
        description="Values that indicate singleton=False"
    )

    # Graph/lineage settings
    max_lineage_depth: int = Field(default=10, description="Max depth for lineage queries")
    max_children_per_query: int = Field(default=10000, description="Max children in recursive queries")

    # Default printer settings
    default_label_style: str = Field(default="tube_2inX1in", description="Default label style")
    default_lab_code: str = Field(default="BLOOM", description="Default lab code")

    # Timezone settings
    default_timezone: str = Field(default="US/Eastern", description="Default timezone")

    # Template config paths (relative to bloom_lims)
    config_base_path: str = Field(
        default="config",
        description="Base path for template configuration files"
    )

    # Action execution
    action_max_executions_unlimited: str = Field(
        default="-1",
        description="Value indicating unlimited action executions"
    )
    action_enabled_true: str = Field(default="1", description="Action enabled value")
    action_enabled_false: str = Field(default="0", description="Action disabled value")


class BloomSettings(BaseSettings):
    """
    Main settings class for BLOOM LIMS.

    Configuration is loaded from environment variables with the BLOOM_ prefix.
    Nested settings use double underscore separator.

    Examples:
        BLOOM_DATABASE__HOST=localhost
        BLOOM_DATABASE__PORT=5432
        BLOOM_API__PAGINATION_DEFAULT_SIZE=100
    """

    model_config = SettingsConfigDict(
        env_prefix="BLOOM_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # Application info
    app_name: str = Field(default="BLOOM LIMS", description="Application name")
    environment: str = Field(default="development", description="Environment name")
    debug: bool = Field(default=False, description="Debug mode")

    # Nested settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    api: APISettings = Field(default_factory=APISettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    constants: BusinessConstants = Field(default_factory=BusinessConstants)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment value."""
        valid_envs = ["development", "staging", "production", "testing"]
        if v.lower() not in valid_envs:
            raise ValueError(f"Environment must be one of: {', '.join(valid_envs)}")
        return v.lower()

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment == "development"


@lru_cache()
def get_settings() -> BloomSettings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    Call get_settings.cache_clear() to reload settings.

    Returns:
        BloomSettings instance with all configuration
    """
    return BloomSettings()


def validate_settings() -> List[str]:
    """
    Validate settings and return list of warnings/issues.

    This should be called on application startup to catch
    configuration issues early.

    Returns:
        List of warning messages (empty if all good)
    """
    warnings = []
    settings = get_settings()

    # Check database settings
    if not settings.database.password and settings.is_production:
        warnings.append("Database password is not set in production")

    # Check auth settings
    if not all(
        [
            settings.auth.cognito_user_pool_id,
            settings.auth.cognito_client_id,
            settings.auth.cognito_region,
            settings.auth.cognito_domain,
            settings.auth.cognito_redirect_uri,
        ]
    ):
        warnings.append("Cognito configuration is incomplete")

    if not settings.auth.jwt_secret and settings.is_production:
        warnings.append("JWT secret is not set in production")

    # Check storage settings
    upload_path = Path(settings.storage.upload_dir)
    if not upload_path.exists():
        warnings.append(f"Upload directory does not exist: {settings.storage.upload_dir}")

    # Check for S3 configuration if bucket is specified
    if settings.storage.s3_bucket:
        if not os.environ.get("AWS_ACCESS_KEY_ID"):
            warnings.append("S3 bucket configured but AWS_ACCESS_KEY_ID not set")

    return warnings


# Legacy compatibility - allow direct imports of common values
def get_database_url() -> str:
    """Get database connection string for backward compatibility."""
    return get_settings().database.connection_string


def get_cognito_config() -> tuple:
    """Get Cognito configuration for backward compatibility."""
    settings = get_settings()
    return (
        settings.auth.cognito_region,
        settings.auth.cognito_user_pool_id,
        settings.auth.cognito_client_id,
    )
