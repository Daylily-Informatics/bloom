"""
BLOOM LIMS Migration Utilities

Helper functions for database migrations.
"""

import os
import logging
from typing import Optional

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def get_alembic_config(alembic_ini_path: Optional[str] = None) -> Config:
    """
    Get Alembic configuration.
    
    Args:
        alembic_ini_path: Path to alembic.ini. If None, uses default location.
        
    Returns:
        Alembic Config object
    """
    if alembic_ini_path is None:
        # Default to project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        alembic_ini_path = os.path.join(project_root, "alembic.ini")
    
    if not os.path.exists(alembic_ini_path):
        raise FileNotFoundError(f"Alembic config not found: {alembic_ini_path}")
    
    config = Config(alembic_ini_path)
    return config


def run_migrations(target: str = "head") -> None:
    """
    Run database migrations to a target revision.
    
    Args:
        target: Target revision (default: "head" for latest)
    """
    config = get_alembic_config()
    logger.info(f"Running migrations to: {target}")
    command.upgrade(config, target)
    logger.info("Migrations completed successfully")


def get_current_revision() -> Optional[str]:
    """
    Get the current database revision.
    
    Returns:
        Current revision string or None if not initialized
    """
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine
    
    from bloom_lims.migrations.env import get_database_url
    
    engine = create_engine(get_database_url())
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        return context.get_current_revision()


def create_migration(message: str, autogenerate: bool = True) -> str:
    """
    Create a new migration.
    
    Args:
        message: Migration description
        autogenerate: Whether to autogenerate from model changes
        
    Returns:
        Path to the new migration file
    """
    config = get_alembic_config()
    
    if autogenerate:
        return command.revision(config, message=message, autogenerate=True)
    else:
        return command.revision(config, message=message)


def rollback(steps: int = 1) -> None:
    """
    Rollback migrations.
    
    Args:
        steps: Number of migrations to rollback
    """
    config = get_alembic_config()
    target = f"-{steps}" if steps > 0 else "base"
    logger.info(f"Rolling back {steps} migration(s)")
    command.downgrade(config, target)
    logger.info("Rollback completed successfully")


def show_history() -> None:
    """Show migration history."""
    config = get_alembic_config()
    command.history(config)


def stamp_baseline() -> None:
    """
    Stamp the database with the baseline revision.
    
    Use this on an existing database that was created with
    postgres_schema_v3.sql to register it with Alembic.
    """
    config = get_alembic_config()
    logger.info("Stamping database with baseline revision")
    command.stamp(config, "0001_baseline")
    logger.info("Database stamped successfully")


# CLI interface when run directly
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python -m bloom_lims.migrations.utils <command>")
        print("Commands: upgrade, current, history, stamp-baseline, rollback")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "upgrade":
        target = sys.argv[2] if len(sys.argv) > 2 else "head"
        run_migrations(target)
    elif cmd == "current":
        rev = get_current_revision()
        print(f"Current revision: {rev}")
    elif cmd == "history":
        show_history()
    elif cmd == "stamp-baseline":
        stamp_baseline()
    elif cmd == "rollback":
        steps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        rollback(steps)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

