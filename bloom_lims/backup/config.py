"""
Backup Configuration Module

Handles configuration for backup operations including storage backends,
retention policies, and scheduling options.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class StorageType(Enum):
    """Supported storage backends for backups."""
    LOCAL = "local"
    S3 = "s3"


class BackupType(Enum):
    """Types of database backups."""
    FULL = "full"           # Complete database dump
    SCHEMA_ONLY = "schema"  # Schema without data
    DATA_ONLY = "data"      # Data without schema


@dataclass
class RetentionPolicy:
    """Backup retention configuration."""
    daily_backups: int = 7      # Keep last 7 daily backups
    weekly_backups: int = 4     # Keep last 4 weekly backups
    monthly_backups: int = 12   # Keep last 12 monthly backups
    min_backups: int = 3        # Always keep at least 3 backups


@dataclass
class S3Config:
    """AWS S3 storage configuration."""
    bucket: str = ""
    prefix: str = "bloom-backups/"
    region: str = "us-east-1"
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    endpoint_url: Optional[str] = None  # For S3-compatible storage (MinIO, etc.)
    storage_class: str = "STANDARD_IA"  # Infrequent Access for cost savings
    
    @classmethod
    def from_env(cls) -> 'S3Config':
        """Create S3Config from environment variables."""
        return cls(
            bucket=os.getenv('BLOOM_BACKUP_S3_BUCKET', ''),
            prefix=os.getenv('BLOOM_BACKUP_S3_PREFIX', 'bloom-backups/'),
            region=os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
            access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            endpoint_url=os.getenv('BLOOM_BACKUP_S3_ENDPOINT'),
            storage_class=os.getenv('BLOOM_BACKUP_S3_STORAGE_CLASS', 'STANDARD_IA'),
        )


@dataclass
class LocalConfig:
    """Local filesystem storage configuration."""
    backup_dir: str = "/var/lib/bloom/backups"
    temp_dir: str = "/tmp/bloom_backup"
    
    @classmethod
    def from_env(cls) -> 'LocalConfig':
        """Create LocalConfig from environment variables."""
        return cls(
            backup_dir=os.getenv('BLOOM_BACKUP_LOCAL_DIR', '/var/lib/bloom/backups'),
            temp_dir=os.getenv('BLOOM_BACKUP_TEMP_DIR', '/tmp/bloom_backup'),
        )


@dataclass
class DatabaseConfig:
    """PostgreSQL database connection configuration."""
    host: str = "localhost"
    port: int = 5432
    database: str = "bloom_lims"
    user: str = "postgres"
    password: str = ""
    
    @classmethod
    def from_env(cls) -> 'DatabaseConfig':
        """Create DatabaseConfig from environment variables."""
        return cls(
            host=os.getenv('PGHOST', os.getenv('BLOOM_DB_HOST', 'localhost')),
            port=int(os.getenv('PGPORT', os.getenv('BLOOM_DB_PORT', '5432'))),
            database=os.getenv('PGDATABASE', os.getenv('BLOOM_DB_NAME', 'bloom_lims')),
            user=os.getenv('PGUSER', os.getenv('BLOOM_DB_USER', 'postgres')),
            password=os.getenv('PGPASSWORD', os.getenv('BLOOM_DB_PASSWORD', '')),
        )
    
    def to_env_dict(self) -> dict:
        """Return environment variables for pg_dump/pg_restore."""
        return {
            'PGHOST': self.host,
            'PGPORT': str(self.port),
            'PGDATABASE': self.database,
            'PGUSER': self.user,
            'PGPASSWORD': self.password,
        }


@dataclass
class BackupConfig:
    """Main backup configuration."""
    storage_type: StorageType = StorageType.LOCAL
    backup_type: BackupType = BackupType.FULL
    compression: bool = True
    compression_level: int = 6  # 1-9, higher = more compression
    parallel_jobs: int = 4      # For pg_dump parallel mode
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)
    s3: S3Config = field(default_factory=S3Config)
    local: LocalConfig = field(default_factory=LocalConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    
    # Notification settings
    notify_on_success: bool = False
    notify_on_failure: bool = True
    notification_email: Optional[str] = None
    
    # Verification settings
    verify_backup: bool = True
    checksum_algorithm: str = "sha256"
    
    @classmethod
    def from_env(cls) -> 'BackupConfig':
        """Create BackupConfig from environment variables."""
        storage_type_str = os.getenv('BLOOM_BACKUP_STORAGE', 'local').lower()
        storage_type = StorageType(storage_type_str) if storage_type_str in ['local', 's3'] else StorageType.LOCAL
        
        return cls(
            storage_type=storage_type,
            compression=os.getenv('BLOOM_BACKUP_COMPRESS', 'true').lower() == 'true',
            compression_level=int(os.getenv('BLOOM_BACKUP_COMPRESS_LEVEL', '6')),
            parallel_jobs=int(os.getenv('BLOOM_BACKUP_PARALLEL_JOBS', '4')),
            s3=S3Config.from_env(),
            local=LocalConfig.from_env(),
            database=DatabaseConfig.from_env(),
            verify_backup=os.getenv('BLOOM_BACKUP_VERIFY', 'true').lower() == 'true',
            notify_on_failure=os.getenv('BLOOM_BACKUP_NOTIFY_FAILURE', 'true').lower() == 'true',
            notification_email=os.getenv('BLOOM_BACKUP_NOTIFY_EMAIL'),
        )

