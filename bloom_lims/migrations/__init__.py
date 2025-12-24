"""
BLOOM LIMS Database Migrations

This package contains Alembic database migrations for BLOOM LIMS.

Usage:
    # Generate a new migration after model changes
    alembic revision --autogenerate -m "description"
    
    # Apply all pending migrations
    alembic upgrade head
    
    # Rollback one migration
    alembic downgrade -1
    
    # Show current revision
    alembic current
    
    # Show migration history
    alembic history

Note: BLOOM uses a hybrid approach where the initial schema is defined
in SQL (postgres_schema_v3.sql) and Alembic is used for subsequent changes.
"""

