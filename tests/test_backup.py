"""
Tests for BLOOM LIMS Backup Module

These tests cover the backup configuration, storage backends, and backup manager.
Some tests use mocking to avoid requiring actual database or S3 connections.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from bloom_lims.backup.config import (
    BackupConfig,
    BackupType,
    StorageType,
    RetentionPolicy,
    S3Config,
    LocalConfig,
    DatabaseConfig,
)
from bloom_lims.backup.storage import LocalStorage, BackupMetadata


class TestBackupConfig:
    """Tests for backup configuration classes."""

    def test_storage_type_enum(self):
        """Test StorageType enum values."""
        assert StorageType.LOCAL.value == "local"
        assert StorageType.S3.value == "s3"

    def test_backup_type_enum(self):
        """Test BackupType enum values."""
        assert BackupType.FULL.value == "full"
        assert BackupType.SCHEMA_ONLY.value == "schema"
        assert BackupType.DATA_ONLY.value == "data"

    def test_retention_policy_defaults(self):
        """Test RetentionPolicy default values."""
        policy = RetentionPolicy()
        assert policy.daily_backups == 7
        assert policy.weekly_backups == 4
        assert policy.monthly_backups == 12
        assert policy.min_backups == 3

    def test_database_config_defaults(self):
        """Test DatabaseConfig default values."""
        config = DatabaseConfig()
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "bloom_lims"
        assert config.user == "postgres"

    def test_database_config_to_env_dict(self):
        """Test DatabaseConfig environment dict generation."""
        config = DatabaseConfig(
            host="dbhost",
            port=5433,
            database="testdb",
            user="testuser",
            password="testpass"
        )
        env = config.to_env_dict()
        assert env['PGHOST'] == "dbhost"
        assert env['PGPORT'] == "5433"
        assert env['PGDATABASE'] == "testdb"
        assert env['PGUSER'] == "testuser"
        assert env['PGPASSWORD'] == "testpass"

    def test_database_config_from_env(self):
        """Test DatabaseConfig creation from environment variables."""
        with patch.dict(os.environ, {
            'PGHOST': 'envhost',
            'PGPORT': '5434',
            'PGDATABASE': 'envdb',
            'PGUSER': 'envuser',
            'PGPASSWORD': 'envpass',
        }):
            config = DatabaseConfig.from_env()
            assert config.host == "envhost"
            assert config.port == 5434
            assert config.database == "envdb"
            assert config.user == "envuser"
            assert config.password == "envpass"

    def test_backup_config_defaults(self):
        """Test BackupConfig default values."""
        config = BackupConfig()
        assert config.storage_type == StorageType.LOCAL
        assert config.backup_type == BackupType.FULL
        assert config.compression is True
        assert config.compression_level == 6
        assert config.parallel_jobs == 4
        assert config.verify_backup is True

    def test_s3_config_defaults(self):
        """Test S3Config default values."""
        config = S3Config()
        assert config.prefix == "bloom-backups/"
        assert config.region == "us-east-1"
        assert config.storage_class == "STANDARD_IA"

    def test_local_config_defaults(self):
        """Test LocalConfig default values."""
        config = LocalConfig()
        assert config.backup_dir == "/var/lib/bloom/backups"
        assert config.temp_dir == "/tmp/bloom_backup"


class TestLocalStorage:
    """Tests for local filesystem storage backend."""

    def test_local_storage_init_creates_directories(self):
        """Test that LocalStorage creates backup directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = os.path.join(tmpdir, "backups")
            temp_dir = os.path.join(tmpdir, "temp")
            
            storage = LocalStorage(backup_dir=backup_dir, temp_dir=temp_dir)
            
            assert os.path.exists(backup_dir)
            assert os.path.exists(temp_dir)

    def test_local_storage_save_and_retrieve(self):
        """Test saving and retrieving a backup file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = os.path.join(tmpdir, "backups")
            storage = LocalStorage(backup_dir=backup_dir)
            
            # Create a test file to backup
            test_content = b"test backup content"
            test_file = Path(tmpdir) / "test_backup.dat"
            test_file.write_bytes(test_content)
            
            # Save backup
            backup_id = "test_backup_001"
            location = storage.save(test_file, backup_id)
            
            assert os.path.exists(location)
            assert storage.exists(backup_id)
            
            # Retrieve backup
            retrieved_path = Path(tmpdir) / "retrieved.dat"
            success = storage.retrieve(backup_id, retrieved_path)
            
            assert success
            assert retrieved_path.read_bytes() == test_content

    def test_local_storage_delete(self):
        """Test deleting a backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = os.path.join(tmpdir, "backups")
            storage = LocalStorage(backup_dir=backup_dir)
            
            # Create and save a test backup
            test_file = Path(tmpdir) / "test.dat"
            test_file.write_bytes(b"test")
            backup_id = "test_delete_001"
            storage.save(test_file, backup_id)
            
            assert storage.exists(backup_id)
            
            # Delete backup
            success = storage.delete(backup_id)

            assert success
            assert not storage.exists(backup_id)

    def test_local_storage_list_backups(self):
        """Test listing available backups."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = os.path.join(tmpdir, "backups")
            storage = LocalStorage(backup_dir=backup_dir)

            # Create multiple test backups
            for i in range(3):
                test_file = Path(tmpdir) / f"test_{i}.dat"
                test_file.write_bytes(f"content {i}".encode())
                storage.save(test_file, f"backup_{i:03d}")

            backups = storage.list_backups()

            assert len(backups) == 3
            assert all(isinstance(b, BackupMetadata) for b in backups)

    def test_local_storage_checksum(self):
        """Test checksum calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = LocalStorage(backup_dir=tmpdir)

            test_file = Path(tmpdir) / "checksum_test.dat"
            test_file.write_bytes(b"test content for checksum")

            checksum = storage.calculate_checksum(test_file)

            assert len(checksum) == 64  # SHA256 hex length
            # Verify deterministic
            assert checksum == storage.calculate_checksum(test_file)


class TestBackupManager:
    """Tests for the BackupManager class."""

    @pytest.fixture
    def temp_backup_config(self, tmp_path):
        """Create a config with temp directories."""
        config = BackupConfig()
        config.local.backup_dir = str(tmp_path / "backups")
        config.local.temp_dir = str(tmp_path / "temp")
        return config

    def test_generate_backup_id(self, temp_backup_config):
        """Test backup ID generation format."""
        from bloom_lims.backup.backup_manager import BackupManager

        temp_backup_config.database.database = "testdb"
        manager = BackupManager(temp_backup_config)

        backup_id = manager._generate_backup_id()

        assert backup_id.startswith("bloom_testdb_full_")
        assert len(backup_id) > 20

    def test_build_pg_dump_command_full(self, temp_backup_config):
        """Test pg_dump command generation for full backup."""
        from bloom_lims.backup.backup_manager import BackupManager

        temp_backup_config.backup_type = BackupType.FULL
        temp_backup_config.compression = True
        temp_backup_config.compression_level = 6
        manager = BackupManager(temp_backup_config)

        cmd = manager._build_pg_dump_command(Path("/tmp/test.backup"))

        assert 'pg_dump' in cmd
        assert '-Fc' in cmd
        assert '-Z6' in cmd
        assert '-f' in cmd
        assert '/tmp/test.backup' in cmd

    def test_build_pg_dump_command_schema_only(self, temp_backup_config):
        """Test pg_dump command for schema-only backup."""
        from bloom_lims.backup.backup_manager import BackupManager

        temp_backup_config.backup_type = BackupType.SCHEMA_ONLY
        manager = BackupManager(temp_backup_config)

        cmd = manager._build_pg_dump_command(Path("/tmp/test.backup"))

        assert '--schema-only' in cmd

    def test_build_pg_dump_command_data_only(self, temp_backup_config):
        """Test pg_dump command for data-only backup."""
        from bloom_lims.backup.backup_manager import BackupManager

        temp_backup_config.backup_type = BackupType.DATA_ONLY
        manager = BackupManager(temp_backup_config)

        cmd = manager._build_pg_dump_command(Path("/tmp/test.backup"))

        assert '--data-only' in cmd

    def test_build_pg_restore_command(self, temp_backup_config):
        """Test pg_restore command generation."""
        from bloom_lims.backup.backup_manager import BackupManager

        temp_backup_config.database.database = "testdb"
        manager = BackupManager(temp_backup_config)

        cmd = manager._build_pg_restore_command(Path("/tmp/test.backup"))

        assert 'pg_restore' in cmd
        assert '-d' in cmd
        assert 'testdb' in cmd
        assert '--clean' in cmd
        assert '--if-exists' in cmd

    @patch('bloom_lims.backup.backup_manager.subprocess.run')
    def test_verify_backup_file_success(self, mock_run, temp_backup_config):
        """Test backup verification success."""
        from bloom_lims.backup.backup_manager import BackupManager

        mock_run.return_value = MagicMock(returncode=0, stderr="")

        manager = BackupManager(temp_backup_config)

        result = manager._verify_backup_file(Path("/tmp/test.backup"))

        assert result is True
        mock_run.assert_called_once()

    @patch('bloom_lims.backup.backup_manager.subprocess.run')
    def test_verify_backup_file_failure(self, mock_run, temp_backup_config):
        """Test backup verification failure."""
        from bloom_lims.backup.backup_manager import BackupManager, BackupError

        mock_run.return_value = MagicMock(returncode=1, stderr="verification error")

        manager = BackupManager(temp_backup_config)

        with pytest.raises(BackupError):
            manager._verify_backup_file(Path("/tmp/test.backup"))


class TestBackupCLI:
    """Tests for the backup CLI module."""

    def test_format_size(self):
        """Test human-readable size formatting."""
        from bloom_lims.backup.cli import format_size

        assert "B" in format_size(500)
        assert "KB" in format_size(1024)
        assert "MB" in format_size(1024 * 1024)
        assert "GB" in format_size(1024 * 1024 * 1024)

    def test_format_age(self):
        """Test human-readable age formatting."""
        from bloom_lims.backup.cli import format_age
        from datetime import timedelta, timezone

        now = datetime.now(timezone.utc)

        # Minutes ago
        recent = now - timedelta(minutes=30)
        assert "m ago" in format_age(recent)

        # Hours ago
        hours_ago = now - timedelta(hours=5)
        assert "h ago" in format_age(hours_ago)

        # Days ago
        days_ago = now - timedelta(days=3)
        assert "d ago" in format_age(days_ago)

