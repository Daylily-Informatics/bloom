"""
Backup Manager Module

Core backup and restore functionality for BLOOM LIMS PostgreSQL database.
Supports full, schema-only, and data-only backups with compression.
"""

import os
import subprocess
import logging
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from .config import BackupConfig, StorageType, BackupType
from .storage import LocalStorage, S3Storage, StorageBackend, BackupMetadata

logger = logging.getLogger(__name__)


class BackupError(Exception):
    """Exception raised for backup operation failures."""
    pass


class RestoreError(Exception):
    """Exception raised for restore operation failures."""
    pass


class BackupManager:
    """
    Manages PostgreSQL database backup and restore operations.
    
    Supports:
    - Full database backups (pg_dump custom format)
    - Schema-only backups
    - Data-only backups
    - Compression with configurable levels
    - Local and S3 storage backends
    - Backup verification
    - Retention policy enforcement
    """
    
    def __init__(self, config: Optional[BackupConfig] = None):
        """Initialize BackupManager with configuration."""
        self.config = config or BackupConfig.from_env()
        self.storage = self._init_storage()
    
    def _init_storage(self) -> StorageBackend:
        """Initialize the appropriate storage backend."""
        if self.config.storage_type == StorageType.S3:
            return S3Storage(
                bucket=self.config.s3.bucket,
                prefix=self.config.s3.prefix,
                region=self.config.s3.region,
                access_key_id=self.config.s3.access_key_id,
                secret_access_key=self.config.s3.secret_access_key,
                endpoint_url=self.config.s3.endpoint_url,
                storage_class=self.config.s3.storage_class,
            )
        else:
            return LocalStorage(
                backup_dir=self.config.local.backup_dir,
                temp_dir=self.config.local.temp_dir,
            )
    
    def _generate_backup_id(self) -> str:
        """Generate a unique backup ID based on timestamp."""
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        db_name = self.config.database.database
        backup_type = self.config.backup_type.value
        return f"bloom_{db_name}_{backup_type}_{timestamp}"
    
    def _build_pg_dump_command(self, output_path: Path) -> List[str]:
        """Build the pg_dump command with appropriate options."""
        cmd = ['pg_dump']
        
        # Output format: custom (compressed, supports parallel restore)
        cmd.extend(['-Fc'])
        
        # Compression
        if self.config.compression:
            cmd.extend([f'-Z{self.config.compression_level}'])
        
        # Parallel jobs for large databases
        if self.config.parallel_jobs > 1:
            cmd.extend([f'-j{self.config.parallel_jobs}'])
        
        # Backup type options
        if self.config.backup_type == BackupType.SCHEMA_ONLY:
            cmd.append('--schema-only')
        elif self.config.backup_type == BackupType.DATA_ONLY:
            cmd.append('--data-only')
        
        # Output file
        cmd.extend(['-f', str(output_path)])
        
        # Database name
        cmd.append(self.config.database.database)
        
        return cmd
    
    def _build_pg_restore_command(self, input_path: Path, 
                                   target_db: Optional[str] = None) -> List[str]:
        """Build the pg_restore command."""
        cmd = ['pg_restore']
        
        # Parallel jobs
        if self.config.parallel_jobs > 1:
            cmd.extend([f'-j{self.config.parallel_jobs}'])
        
        # Target database
        db_name = target_db or self.config.database.database
        cmd.extend(['-d', db_name])
        
        # Clean (drop) objects before recreating
        cmd.append('--clean')
        cmd.append('--if-exists')
        
        # Input file
        cmd.append(str(input_path))
        
        return cmd
    
    def create_backup(self, backup_type: Optional[BackupType] = None) -> Tuple[str, str]:
        """
        Create a database backup.
        
        Args:
            backup_type: Override the configured backup type
            
        Returns:
            Tuple of (backup_id, storage_location)
            
        Raises:
            BackupError: If backup creation fails
        """
        if backup_type:
            self.config.backup_type = backup_type
        
        backup_id = self._generate_backup_id()
        logger.info(f"Starting backup: {backup_id}")
        
        # Create temporary file for backup
        with tempfile.NamedTemporaryFile(suffix='.backup', delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
        
        try:
            # Build and execute pg_dump
            cmd = self._build_pg_dump_command(tmp_path)
            env = os.environ.copy()
            env.update(self.config.database.to_env_dict())
            
            logger.debug(f"Executing: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise BackupError(f"pg_dump failed: {result.stderr}")
            
            # Verify backup file was created
            if not tmp_path.exists() or tmp_path.stat().st_size == 0:
                raise BackupError("Backup file is empty or was not created")

            backup_size = tmp_path.stat().st_size
            logger.info(f"Backup created: {backup_size / (1024*1024):.2f} MB")

            # Verify backup integrity if configured
            if self.config.verify_backup:
                self._verify_backup_file(tmp_path)

            # Upload to storage
            storage_location = self.storage.save(tmp_path, backup_id)

            logger.info(f"Backup completed: {backup_id} -> {storage_location}")
            return backup_id, storage_location

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            raise BackupError(str(e)) from e
        finally:
            # Clean up temporary file
            if tmp_path.exists():
                tmp_path.unlink()

    def _verify_backup_file(self, backup_path: Path) -> bool:
        """Verify backup file integrity using pg_restore --list."""
        cmd = ['pg_restore', '--list', str(backup_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise BackupError(f"Backup verification failed: {result.stderr}")

        logger.info("Backup verification passed")
        return True

    def restore_backup(self, backup_id: str, target_db: Optional[str] = None,
                       dry_run: bool = False) -> bool:
        """
        Restore a database from backup.

        Args:
            backup_id: The backup ID to restore
            target_db: Optional target database name (defaults to config)
            dry_run: If True, only verify the backup without restoring

        Returns:
            True if restore was successful

        Raises:
            RestoreError: If restore fails
        """
        logger.info(f"Starting restore: {backup_id}")

        # Check if backup exists
        if not self.storage.exists(backup_id):
            raise RestoreError(f"Backup not found: {backup_id}")

        # Create temporary file for download
        with tempfile.NamedTemporaryFile(suffix='.backup', delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)

        try:
            # Download backup from storage
            if not self.storage.retrieve(backup_id, tmp_path):
                raise RestoreError(f"Failed to retrieve backup: {backup_id}")

            # Verify backup integrity
            self._verify_backup_file(tmp_path)

            if dry_run:
                logger.info("Dry run completed - backup is valid")
                return True

            # Execute pg_restore
            cmd = self._build_pg_restore_command(tmp_path, target_db)
            env = os.environ.copy()
            env.update(self.config.database.to_env_dict())

            logger.warning(f"Restoring database from backup {backup_id}...")
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True
            )

            # pg_restore may return non-zero for warnings, check stderr
            if result.returncode != 0 and 'ERROR' in result.stderr:
                raise RestoreError(f"pg_restore failed: {result.stderr}")

            logger.info(f"Restore completed successfully: {backup_id}")
            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            raise RestoreError(str(e)) from e
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def list_backups(self) -> List[BackupMetadata]:
        """List all available backups."""
        return self.storage.list_backups()

    def delete_backup(self, backup_id: str) -> bool:
        """Delete a specific backup."""
        return self.storage.delete(backup_id)

    def apply_retention_policy(self) -> List[str]:
        """
        Apply retention policy and delete old backups.

        Returns:
            List of deleted backup IDs
        """
        backups = self.list_backups()
        retention = self.config.retention
        deleted = []

        # Always keep minimum number of backups
        if len(backups) <= retention.min_backups:
            logger.info(f"Only {len(backups)} backups exist, keeping all")
            return deleted

        # Group backups by age
        now = datetime.utcnow()
        daily_kept = 0
        weekly_kept = 0
        monthly_kept = 0

        for backup in backups:
            age_days = (now - backup.created_at).days

            # Keep recent daily backups
            if age_days < 7 and daily_kept < retention.daily_backups:
                daily_kept += 1
                continue

            # Keep weekly backups (one per week)
            if age_days < 30 and weekly_kept < retention.weekly_backups:
                if backup.created_at.weekday() == 0:  # Monday
                    weekly_kept += 1
                    continue

            # Keep monthly backups (one per month)
            if age_days < 365 and monthly_kept < retention.monthly_backups:
                if backup.created_at.day == 1:  # First of month
                    monthly_kept += 1
                    continue

            # Delete old backups (but keep minimum)
            if len(backups) - len(deleted) > retention.min_backups:
                if self.delete_backup(backup.backup_id):
                    deleted.append(backup.backup_id)
                    logger.info(f"Deleted old backup: {backup.backup_id}")

        return deleted

