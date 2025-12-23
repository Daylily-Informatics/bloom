"""
Alembic Environment Configuration for BLOOM LIMS

This module configures Alembic to work with the BLOOM LIMS database.
It supports both online (connected to database) and offline (SQL script
generation) migration modes.
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, create_engine
from alembic import context

# Add the project root to the path so we can import bloom_lims modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import BLOOM LIMS models for autogenerate support
from bloom_lims.db import (
    Base,
    generic_template,
    generic_instance,
    generic_instance_lineage,
)

# This is the Alembic Config object
config = context.config

# Setup logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
target_metadata = Base.metadata


def get_database_url() -> str:
    """
    Get the database URL from environment variables.
    
    Uses the same environment variables as BLOOMdb3:
    - PGPASSWORD: PostgreSQL password
    - PGPORT: PostgreSQL port (default: 5445)
    - USER: PostgreSQL user
    """
    db_user = os.environ.get("USER", "bloom")
    db_pass = os.environ.get("PGPASSWORD", "")
    db_port = os.environ.get("PGPORT", "5445")
    db_host = os.environ.get("PGHOST", "localhost")
    db_name = os.environ.get("PGDATABASE", "bloom")
    
    return f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    
    This generates SQL scripts without connecting to the database.
    Useful for reviewing migrations before applying them.
    """
    url = config.get_main_option("sqlalchemy.url")
    if url == "driver://user:pass@localhost/dbname":
        url = get_database_url()
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.
    
    This connects to the database and applies migrations directly.
    """
    # Get URL from config or environment
    url = config.get_main_option("sqlalchemy.url")
    if url == "driver://user:pass@localhost/dbname":
        url = get_database_url()
    
    # Create engine with connection pooling disabled for migrations
    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # Include schemas in autogenerate
            include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# Run the appropriate migration mode
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

