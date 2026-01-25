"""Initial baseline migration - stamps existing schema

This migration does NOT create tables - it establishes a baseline
for the existing BLOOM LIMS schema created by TapDB schema (tapdb_schema.sql).

Run this migration on an existing database to register the current
schema state with Alembic before making any new migrations.

Revision ID: 0001_baseline
Revises: None
Create Date: 2024-12-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Baseline migration - no schema changes.
    
    This migration assumes the database was created using:
    TapDB schema (tapdb_schema.sql) + bloom_prefix_sequences.sql
    
    Tables that should exist:
    - generic_template
    - generic_instance  
    - generic_instance_lineage
    - audit_log
    
    Along with all the polymorphic identity classes:
    - workflow_*, container_*, content_*, equipment_*, etc.
    """
    # Verify core tables exist (will fail if schema not initialized)
    conn = op.get_bind()
    
    # Check for existence of core tables
    result = conn.execute(sa.text("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name IN ('generic_template', 'generic_instance', 'generic_instance_lineage', 'audit_log')
    """))
    
    tables = [row[0] for row in result]
    required_tables = {'generic_template', 'generic_instance', 'generic_instance_lineage', 'audit_log'}
    
    missing = required_tables - set(tables)
    if missing:
        raise RuntimeError(
            f"Baseline migration failed: missing tables {missing}. "
            f"Please run install_postgres.sh first to initialize the database with TapDB schema."
        )
    
    # Log baseline establishment
    print("BLOOM LIMS baseline migration established successfully.")
    print(f"Found tables: {tables}")


def downgrade() -> None:
    """
    Downgrade from baseline - not supported.
    
    The baseline migration cannot be downgraded because it doesn't
    create any schema - it only establishes a reference point.
    To fully reset, drop the database and recreate with install_postgres.sh (TapDB schema).
    """
    raise RuntimeError(
        "Cannot downgrade baseline migration. "
        "To reset, drop the database and recreate with install_postgres.sh"
    )

