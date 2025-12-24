"""
Storage Backend Module

Provides abstract and concrete implementations for backup storage backends.
Supports local filesystem and AWS S3 (including S3-compatible services).
"""

import os
import shutil
import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, BinaryIO
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BackupMetadata:
    """Metadata for a backup file."""
    backup_id: str
    filename: str
    size_bytes: int
    created_at: datetime
    checksum: str
    checksum_algorithm: str
    backup_type: str
    database_name: str
    compressed: bool
    storage_location: str


class StorageBackend(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    def save(self, local_path: Path, backup_id: str) -> str:
        """Save a backup file to storage. Returns the storage location."""
        pass
    
    @abstractmethod
    def retrieve(self, backup_id: str, local_path: Path) -> bool:
        """Retrieve a backup file from storage. Returns success status."""
        pass
    
    @abstractmethod
    def delete(self, backup_id: str) -> bool:
        """Delete a backup from storage. Returns success status."""
        pass
    
    @abstractmethod
    def list_backups(self) -> List[BackupMetadata]:
        """List all available backups."""
        pass
    
    @abstractmethod
    def exists(self, backup_id: str) -> bool:
        """Check if a backup exists."""
        pass
    
    def calculate_checksum(self, file_path: Path, algorithm: str = "sha256") -> str:
        """Calculate checksum of a file."""
        hash_func = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hash_func.update(chunk)
        return hash_func.hexdigest()


class LocalStorage(StorageBackend):
    """Local filesystem storage backend."""
    
    def __init__(self, backup_dir: str, temp_dir: str = "/tmp/bloom_backup"):
        self.backup_dir = Path(backup_dir)
        self.temp_dir = Path(temp_dir)
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Create backup directories if they don't exist."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, local_path: Path, backup_id: str) -> str:
        """Save backup to local storage."""
        dest_path = self.backup_dir / f"{backup_id}.backup"
        shutil.copy2(local_path, dest_path)
        
        # Save metadata
        metadata_path = self.backup_dir / f"{backup_id}.meta"
        checksum = self.calculate_checksum(dest_path)
        metadata = {
            'backup_id': backup_id,
            'filename': dest_path.name,
            'size_bytes': dest_path.stat().st_size,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'checksum': checksum,
            'checksum_algorithm': 'sha256',
        }
        
        import json
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Backup saved to {dest_path}")
        return str(dest_path)
    
    def retrieve(self, backup_id: str, local_path: Path) -> bool:
        """Retrieve backup from local storage."""
        source_path = self.backup_dir / f"{backup_id}.backup"
        if not source_path.exists():
            logger.error(f"Backup not found: {backup_id}")
            return False
        
        shutil.copy2(source_path, local_path)
        logger.info(f"Backup retrieved to {local_path}")
        return True
    
    def delete(self, backup_id: str) -> bool:
        """Delete backup from local storage."""
        backup_path = self.backup_dir / f"{backup_id}.backup"
        metadata_path = self.backup_dir / f"{backup_id}.meta"
        
        try:
            if backup_path.exists():
                backup_path.unlink()
            if metadata_path.exists():
                metadata_path.unlink()
            logger.info(f"Backup deleted: {backup_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete backup {backup_id}: {e}")
            return False
    
    def list_backups(self) -> List[BackupMetadata]:
        """List all local backups."""
        import json
        backups = []
        
        for meta_file in self.backup_dir.glob("*.meta"):
            try:
                with open(meta_file) as f:
                    data = json.load(f)
                backups.append(BackupMetadata(
                    backup_id=data['backup_id'],
                    filename=data['filename'],
                    size_bytes=data['size_bytes'],
                    created_at=datetime.fromisoformat(data['created_at']),
                    checksum=data['checksum'],
                    checksum_algorithm=data.get('checksum_algorithm', 'sha256'),
                    backup_type=data.get('backup_type', 'full'),
                    database_name=data.get('database_name', 'unknown'),
                    compressed=data.get('compressed', True),
                    storage_location=str(self.backup_dir / data['filename']),
                ))
            except Exception as e:
                logger.warning(f"Failed to read metadata {meta_file}: {e}")
        
        return sorted(backups, key=lambda x: x.created_at, reverse=True)
    
    def exists(self, backup_id: str) -> bool:
        """Check if backup exists locally."""
        return (self.backup_dir / f"{backup_id}.backup").exists()


class S3Storage(StorageBackend):
    """AWS S3 storage backend (also supports S3-compatible services like MinIO)."""

    def __init__(self, bucket: str, prefix: str = "bloom-backups/",
                 region: str = "us-east-1", access_key_id: Optional[str] = None,
                 secret_access_key: Optional[str] = None, endpoint_url: Optional[str] = None,
                 storage_class: str = "STANDARD_IA"):
        self.bucket = bucket
        self.prefix = prefix.rstrip('/') + '/'
        self.region = region
        self.storage_class = storage_class
        self.endpoint_url = endpoint_url

        # Initialize boto3 client
        try:
            import boto3
            from botocore.config import Config

            config = Config(
                region_name=region,
                retries={'max_attempts': 3, 'mode': 'adaptive'}
            )

            client_kwargs = {'config': config}
            if endpoint_url:
                client_kwargs['endpoint_url'] = endpoint_url
            if access_key_id and secret_access_key:
                client_kwargs['aws_access_key_id'] = access_key_id
                client_kwargs['aws_secret_access_key'] = secret_access_key

            self.s3_client = boto3.client('s3', **client_kwargs)
            self.s3_resource = boto3.resource('s3', **client_kwargs)
            logger.info(f"S3 storage initialized: bucket={bucket}, prefix={prefix}")
        except ImportError:
            raise ImportError("boto3 is required for S3 storage. Install with: pip install boto3")

    def _get_key(self, backup_id: str, suffix: str = ".backup") -> str:
        """Get the S3 key for a backup."""
        return f"{self.prefix}{backup_id}{suffix}"

    def save(self, local_path: Path, backup_id: str) -> str:
        """Upload backup to S3."""
        import json

        backup_key = self._get_key(backup_id, ".backup")
        metadata_key = self._get_key(backup_id, ".meta")

        # Calculate checksum before upload
        checksum = self.calculate_checksum(local_path)

        # Upload backup file
        extra_args = {
            'StorageClass': self.storage_class,
            'Metadata': {
                'backup_id': backup_id,
                'checksum': checksum,
                'checksum_algorithm': 'sha256',
            }
        }

        self.s3_client.upload_file(
            str(local_path),
            self.bucket,
            backup_key,
            ExtraArgs=extra_args
        )

        # Upload metadata
        metadata = {
            'backup_id': backup_id,
            'filename': f"{backup_id}.backup",
            'size_bytes': local_path.stat().st_size,
            'created_at': datetime.utcnow().isoformat(),
            'checksum': checksum,
            'checksum_algorithm': 'sha256',
            's3_key': backup_key,
        }

        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=metadata_key,
            Body=json.dumps(metadata, indent=2),
            ContentType='application/json'
        )

        location = f"s3://{self.bucket}/{backup_key}"
        logger.info(f"Backup uploaded to {location}")
        return location

    def retrieve(self, backup_id: str, local_path: Path) -> bool:
        """Download backup from S3."""
        backup_key = self._get_key(backup_id, ".backup")

        try:
            self.s3_client.download_file(self.bucket, backup_key, str(local_path))
            logger.info(f"Backup downloaded to {local_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to download backup {backup_id}: {e}")
            return False

    def delete(self, backup_id: str) -> bool:
        """Delete backup from S3."""
        backup_key = self._get_key(backup_id, ".backup")
        metadata_key = self._get_key(backup_id, ".meta")

        try:
            self.s3_client.delete_objects(
                Bucket=self.bucket,
                Delete={
                    'Objects': [
                        {'Key': backup_key},
                        {'Key': metadata_key},
                    ]
                }
            )
            logger.info(f"Backup deleted from S3: {backup_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete backup {backup_id}: {e}")
            return False

    def list_backups(self) -> List[BackupMetadata]:
        """List all S3 backups."""
        import json
        backups = []

        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                for obj in page.get('Contents', []):
                    if obj['Key'].endswith('.meta'):
                        try:
                            response = self.s3_client.get_object(
                                Bucket=self.bucket,
                                Key=obj['Key']
                            )
                            data = json.loads(response['Body'].read().decode('utf-8'))
                            backups.append(BackupMetadata(
                                backup_id=data['backup_id'],
                                filename=data['filename'],
                                size_bytes=data['size_bytes'],
                                created_at=datetime.fromisoformat(data['created_at']),
                                checksum=data['checksum'],
                                checksum_algorithm=data.get('checksum_algorithm', 'sha256'),
                                backup_type=data.get('backup_type', 'full'),
                                database_name=data.get('database_name', 'unknown'),
                                compressed=data.get('compressed', True),
                                storage_location=f"s3://{self.bucket}/{data.get('s3_key', '')}",
                            ))
                        except Exception as e:
                            logger.warning(f"Failed to read metadata {obj['Key']}: {e}")
        except Exception as e:
            logger.error(f"Failed to list S3 backups: {e}")

        return sorted(backups, key=lambda x: x.created_at, reverse=True)

    def exists(self, backup_id: str) -> bool:
        """Check if backup exists in S3."""
        backup_key = self._get_key(backup_id, ".backup")
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=backup_key)
            return True
        except:
            return False

