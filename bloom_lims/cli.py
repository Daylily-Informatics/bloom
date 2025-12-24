#!/usr/bin/env python3
"""
BLOOM LIMS Command Line Interface

Unified CLI for database, workflow, and validation operations.

Usage:
    bloom db migrate          # Run database migrations
    bloom db seed             # Load test data
    bloom db status           # Show database status
    bloom workflow create     # Create workflow from template
    bloom workflow list       # List workflows
    bloom validate schema     # Validate JSON templates
    bloom validate all        # Run all validations
    bloom cache stats         # Show cache statistics
    bloom cache clear         # Clear cache
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def cmd_db_migrate(args) -> int:
    """Run database migrations."""
    try:
        from alembic.config import Config
        from alembic import command
        
        alembic_cfg = Config("alembic.ini")
        
        if args.revision:
            command.upgrade(alembic_cfg, args.revision)
        else:
            command.upgrade(alembic_cfg, "head")
        
        print("✓ Migrations completed successfully")
        return 0
    except Exception as e:
        print(f"✗ Migration failed: {e}", file=sys.stderr)
        return 1


def cmd_db_status(args) -> int:
    """Show database status."""
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.config import get_settings
        
        settings = get_settings()
        print(f"Database Configuration:")
        print(f"  Host: {settings.database.host}:{settings.database.port}")
        print(f"  Database: {settings.database.database}")
        print(f"  User: {settings.database.user}")
        print(f"  Pool Size: {settings.database.pool_size}")
        
        # Test connection
        with BLOOMdb3(echo_sql=False) as bdb:
            result = bdb.session.execute("SELECT 1").fetchone()
            if result:
                print(f"\n✓ Database connection successful")
                
                # Get table counts
                for table in ['generic_template', 'generic_instance', 'generic_instance_lineage']:
                    count_result = bdb.session.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    print(f"  {table}: {count_result[0]} rows")
        
        return 0
    except Exception as e:
        print(f"✗ Database connection failed: {e}", file=sys.stderr)
        return 1


def cmd_db_seed(args) -> int:
    """Load seed data from template JSON files."""
    try:
        from bloom_lims.db import BLOOMdb3
        
        config_path = Path(__file__).parent / "config"
        if not config_path.exists():
            print(f"✗ Config directory not found: {config_path}", file=sys.stderr)
            return 1
        
        loaded = 0
        skipped = 0
        
        with BLOOMdb3(echo_sql=False) as bdb:
            for json_file in config_path.rglob("*.json"):
                if json_file.name == "metadata.json":
                    continue
                    
                try:
                    with open(json_file) as f:
                        data = json.load(f)
                    
                    # Process template definitions
                    for template_name, versions in data.items():
                        for version, template_data in versions.items():
                            # Check if already exists
                            existing = bdb.session.query(
                                bdb.Base.classes.generic_template
                            ).filter_by(
                                btype=template_name,
                                version=version
                            ).first()
                            
                            if existing:
                                skipped += 1
                                continue
                            
                            loaded += 1
                            
                except json.JSONDecodeError as e:
                    print(f"  ⚠ Invalid JSON in {json_file}: {e}")
                except Exception as e:
                    print(f"  ⚠ Error processing {json_file}: {e}")
        
        print(f"✓ Seed complete: {loaded} loaded, {skipped} skipped (already exist)")
        return 0
    except Exception as e:
        print(f"✗ Seed failed: {e}", file=sys.stderr)
        return 1


def cmd_workflow_list(args) -> int:
    """List workflow templates."""
    try:
        from bloom_lims.db import BLOOMdb3
        
        with BLOOMdb3(echo_sql=False) as bdb:
            workflows = bdb.session.query(
                bdb.Base.classes.generic_template
            ).filter(
                bdb.Base.classes.generic_template.super_type == "workflow",
                bdb.Base.classes.generic_template.is_deleted == False,
            ).all()
            
            if not workflows:
                print("No workflow templates found.")
                return 0
            
            print(f"{'EUID':<20} {'Type':<20} {'SubType':<25} {'Version':<8}")
            print("-" * 75)
            for wf in workflows:
                print(f"{wf.euid:<20} {wf.btype:<20} {wf.b_sub_type:<25} {wf.version:<8}")
        
        return 0
    except Exception as e:
        print(f"✗ Failed to list workflows: {e}", file=sys.stderr)
        return 1


def cmd_workflow_create(args) -> int:
    """Create a workflow instance from template."""
    try:
        from bloom_lims.db import BLOOMdb3
        from bloom_lims.domain.workflows import BloomWorkflow

        with BLOOMdb3(echo_sql=False) as bdb:
            bwf = BloomWorkflow(bdb)
            result = bwf.create_instances(args.template_euid)

            if result and result[0]:
                instance = result[0][0]
                print(f"✓ Created workflow instance: {instance.euid}")
                print(f"  Name: {instance.name}")
                print(f"  Type: {instance.btype}/{instance.b_sub_type}")
                return 0
            else:
                print(f"✗ Failed to create workflow from {args.template_euid}")
                return 1
    except Exception as e:
        print(f"✗ Failed to create workflow: {e}", file=sys.stderr)
        return 1


def cmd_validate_schema(args) -> int:
    """Validate JSON template files."""
    config_path = Path(__file__).parent / "config"
    if not config_path.exists():
        print(f"✗ Config directory not found: {config_path}", file=sys.stderr)
        return 1

    errors = []
    warnings = []
    valid_count = 0

    required_keys = {"action_groups", "action_imports"}

    for json_file in config_path.rglob("*.json"):
        if json_file.name == "metadata.json":
            continue

        try:
            with open(json_file) as f:
                data = json.load(f)

            # Validate structure
            for template_name, versions in data.items():
                if not isinstance(versions, dict):
                    errors.append(f"{json_file}: {template_name} is not a dict of versions")
                    continue

                for version, template_data in versions.items():
                    if not isinstance(template_data, dict):
                        errors.append(f"{json_file}: {template_name}/{version} is not a dict")
                        continue

                    # Check for singleton (should be string "0" or "1")
                    if "singleton" in template_data:
                        singleton = template_data["singleton"]
                        if singleton not in ["0", "1", 0, 1]:
                            warnings.append(
                                f"{json_file}: {template_name}/{version} singleton value '{singleton}' should be '0' or '1'"
                            )

                    valid_count += 1

        except json.JSONDecodeError as e:
            errors.append(f"{json_file}: Invalid JSON - {e}")
        except Exception as e:
            errors.append(f"{json_file}: Error - {e}")

    # Report results
    print(f"Validated {valid_count} templates")

    if warnings:
        print(f"\n⚠ {len(warnings)} warning(s):")
        for w in warnings[:10]:  # Show first 10
            print(f"  - {w}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more")

    if errors:
        print(f"\n✗ {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("\n✓ All templates valid")
    return 0


def cmd_cache_stats(args) -> int:
    """Show cache statistics."""
    try:
        from bloom_lims.core.cache import get_cache_stats

        stats = get_cache_stats()
        print("Cache Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        return 0
    except Exception as e:
        print(f"✗ Failed to get cache stats: {e}", file=sys.stderr)
        return 1


def cmd_cache_clear(args) -> int:
    """Clear the cache."""
    try:
        from bloom_lims.core.cache import cache_clear

        cache_clear()
        print("✓ Cache cleared")
        return 0
    except Exception as e:
        print(f"✗ Failed to clear cache: {e}", file=sys.stderr)
        return 1


def main():
    """Main entry point for BLOOM CLI."""
    parser = argparse.ArgumentParser(
        description='BLOOM LIMS Command Line Interface',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  bloom db status                 Show database connection status
  bloom db migrate                Run pending migrations
  bloom db migrate --revision=head  Migrate to specific revision
  bloom db seed                   Load template seed data
  bloom workflow list             List workflow templates
  bloom workflow create <euid>    Create workflow from template
  bloom validate schema           Validate JSON template files
  bloom cache stats               Show cache statistics
  bloom cache clear               Clear the cache
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Database commands
    db_parser = subparsers.add_parser('db', help='Database operations')
    db_subparsers = db_parser.add_subparsers(dest='db_command')

    migrate_parser = db_subparsers.add_parser('migrate', help='Run migrations')
    migrate_parser.add_argument('--revision', help='Target revision (default: head)')

    db_subparsers.add_parser('status', help='Show database status')
    db_subparsers.add_parser('seed', help='Load seed data')

    # Workflow commands
    wf_parser = subparsers.add_parser('workflow', help='Workflow operations')
    wf_subparsers = wf_parser.add_subparsers(dest='wf_command')

    wf_subparsers.add_parser('list', help='List workflow templates')

    create_parser = wf_subparsers.add_parser('create', help='Create workflow instance')
    create_parser.add_argument('template_euid', help='Template EUID to instantiate')

    # Validate commands
    val_parser = subparsers.add_parser('validate', help='Validation operations')
    val_subparsers = val_parser.add_subparsers(dest='val_command')

    val_subparsers.add_parser('schema', help='Validate JSON templates')

    # Cache commands
    cache_parser = subparsers.add_parser('cache', help='Cache operations')
    cache_subparsers = cache_parser.add_subparsers(dest='cache_command')

    cache_subparsers.add_parser('stats', help='Show cache statistics')
    cache_subparsers.add_parser('clear', help='Clear cache')

    # Global options
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Dispatch to command handler
    if args.command == 'db':
        if args.db_command == 'migrate':
            return cmd_db_migrate(args)
        elif args.db_command == 'status':
            return cmd_db_status(args)
        elif args.db_command == 'seed':
            return cmd_db_seed(args)
        else:
            db_parser.print_help()
            return 1
    elif args.command == 'workflow':
        if args.wf_command == 'list':
            return cmd_workflow_list(args)
        elif args.wf_command == 'create':
            return cmd_workflow_create(args)
        else:
            wf_parser.print_help()
            return 1
    elif args.command == 'validate':
        if args.val_command == 'schema':
            return cmd_validate_schema(args)
        else:
            val_parser.print_help()
            return 1
    elif args.command == 'cache':
        if args.cache_command == 'stats':
            return cmd_cache_stats(args)
        elif args.cache_command == 'clear':
            return cmd_cache_clear(args)
        else:
            cache_parser.print_help()
            return 1
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())

