#!/usr/bin/env python3
"""
BLOOM LIMS Backup CLI

Command-line interface for database backup and restore operations.

Usage:
    bloom-backup create [--type=full|schema|data] [--storage=local|s3]
    bloom-backup restore <backup_id> [--target-db=<name>] [--dry-run]
    bloom-backup list [--format=table|json]
    bloom-backup delete <backup_id> [--force]
    bloom-backup verify <backup_id>
    bloom-backup cleanup [--dry-run]
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from typing import Optional

from .backup_manager import BackupManager, BackupError, RestoreError
from .config import BackupConfig, BackupType, StorageType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def format_age(dt: datetime) -> str:
    """Format datetime as human-readable age."""
    delta = datetime.utcnow() - dt
    if delta.days > 0:
        return f"{delta.days}d ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    minutes = delta.seconds // 60
    return f"{minutes}m ago"


def cmd_create(args, manager: BackupManager) -> int:
    """Create a new backup."""
    backup_type = None
    if args.type:
        backup_type = BackupType(args.type)
    
    try:
        backup_id, location = manager.create_backup(backup_type)
        print(f"✓ Backup created successfully")
        print(f"  ID: {backup_id}")
        print(f"  Location: {location}")
        return 0
    except BackupError as e:
        print(f"✗ Backup failed: {e}", file=sys.stderr)
        return 1


def cmd_restore(args, manager: BackupManager) -> int:
    """Restore from a backup."""
    try:
        if args.dry_run:
            print(f"Verifying backup {args.backup_id}...")
        else:
            print(f"⚠ WARNING: This will overwrite the database!")
            if not args.force:
                confirm = input("Type 'yes' to continue: ")
                if confirm.lower() != 'yes':
                    print("Restore cancelled.")
                    return 1
        
        success = manager.restore_backup(
            args.backup_id,
            target_db=args.target_db,
            dry_run=args.dry_run
        )
        
        if success:
            if args.dry_run:
                print(f"✓ Backup {args.backup_id} is valid and can be restored")
            else:
                print(f"✓ Database restored successfully from {args.backup_id}")
            return 0
        return 1
    except RestoreError as e:
        print(f"✗ Restore failed: {e}", file=sys.stderr)
        return 1


def cmd_list(args, manager: BackupManager) -> int:
    """List available backups."""
    backups = manager.list_backups()
    
    if not backups:
        print("No backups found.")
        return 0
    
    if args.format == 'json':
        output = [
            {
                'backup_id': b.backup_id,
                'created_at': b.created_at.isoformat(),
                'size_bytes': b.size_bytes,
                'backup_type': b.backup_type,
                'storage_location': b.storage_location,
            }
            for b in backups
        ]
        print(json.dumps(output, indent=2))
    else:
        # Table format
        print(f"{'Backup ID':<45} {'Created':<12} {'Size':<10} {'Type':<8}")
        print("-" * 80)
        for b in backups:
            print(f"{b.backup_id:<45} {format_age(b.created_at):<12} "
                  f"{format_size(b.size_bytes):<10} {b.backup_type:<8}")
    
    return 0


def cmd_delete(args, manager: BackupManager) -> int:
    """Delete a backup."""
    if not args.force:
        confirm = input(f"Delete backup {args.backup_id}? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Delete cancelled.")
            return 1
    
    if manager.delete_backup(args.backup_id):
        print(f"✓ Backup {args.backup_id} deleted")
        return 0
    else:
        print(f"✗ Failed to delete backup {args.backup_id}", file=sys.stderr)
        return 1


def cmd_verify(args, manager: BackupManager) -> int:
    """Verify a backup's integrity."""
    try:
        success = manager.restore_backup(args.backup_id, dry_run=True)
        if success:
            print(f"✓ Backup {args.backup_id} is valid")
            return 0
        return 1
    except RestoreError as e:
        print(f"✗ Backup verification failed: {e}", file=sys.stderr)
        return 1


def cmd_cleanup(args, manager: BackupManager) -> int:
    """Apply retention policy and clean up old backups."""
    if args.dry_run:
        print("Dry run - no backups will be deleted")

    deleted = manager.apply_retention_policy()

    if deleted:
        print(f"Deleted {len(deleted)} old backup(s):")
        for backup_id in deleted:
            print(f"  - {backup_id}")
    else:
        print("No backups to clean up")

    return 0


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description='BLOOM LIMS Database Backup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  bloom-backup create                    Create a full backup
  bloom-backup create --type=schema      Create schema-only backup
  bloom-backup create --storage=s3       Create backup and upload to S3
  bloom-backup list                      List all backups
  bloom-backup restore <backup_id>       Restore from backup
  bloom-backup verify <backup_id>        Verify backup integrity
  bloom-backup cleanup                   Apply retention policy

Environment Variables:
  BLOOM_BACKUP_STORAGE          Storage type: local or s3
  BLOOM_BACKUP_LOCAL_DIR        Local backup directory
  BLOOM_BACKUP_S3_BUCKET        S3 bucket name
  BLOOM_BACKUP_S3_PREFIX        S3 key prefix
  PGHOST, PGPORT, PGDATABASE    PostgreSQL connection settings
  PGUSER, PGPASSWORD            PostgreSQL credentials
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Create command
    create_parser = subparsers.add_parser('create', help='Create a new backup')
    create_parser.add_argument('--type', choices=['full', 'schema', 'data'],
                               default='full', help='Backup type')
    create_parser.add_argument('--storage', choices=['local', 's3'],
                               help='Storage backend (overrides env)')

    # Restore command
    restore_parser = subparsers.add_parser('restore', help='Restore from backup')
    restore_parser.add_argument('backup_id', help='Backup ID to restore')
    restore_parser.add_argument('--target-db', help='Target database name')
    restore_parser.add_argument('--dry-run', action='store_true',
                                help='Verify backup without restoring')
    restore_parser.add_argument('--force', action='store_true',
                                help='Skip confirmation prompt')

    # List command
    list_parser = subparsers.add_parser('list', help='List available backups')
    list_parser.add_argument('--format', choices=['table', 'json'],
                             default='table', help='Output format')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a backup')
    delete_parser.add_argument('backup_id', help='Backup ID to delete')
    delete_parser.add_argument('--force', action='store_true',
                               help='Skip confirmation prompt')

    # Verify command
    verify_parser = subparsers.add_parser('verify', help='Verify backup integrity')
    verify_parser.add_argument('backup_id', help='Backup ID to verify')

    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Apply retention policy')
    cleanup_parser.add_argument('--dry-run', action='store_true',
                                help='Show what would be deleted')

    # Global options
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.command:
        parser.print_help()
        return 1

    # Initialize config and manager
    config = BackupConfig.from_env()

    # Override storage if specified
    if hasattr(args, 'storage') and args.storage:
        config.storage_type = StorageType(args.storage)

    manager = BackupManager(config)

    # Dispatch to command handler
    commands = {
        'create': cmd_create,
        'restore': cmd_restore,
        'list': cmd_list,
        'delete': cmd_delete,
        'verify': cmd_verify,
        'cleanup': cmd_cleanup,
    }

    return commands[args.command](args, manager)


if __name__ == '__main__':
    sys.exit(main())

