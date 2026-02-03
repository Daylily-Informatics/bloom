"""Add missing EUID sequences for DAT, LM, HEV prefixes

This migration adds the missing PostgreSQL sequences required by the
set_generic_instance_euid() trigger for template prefixes that were
added to metadata.json files but not to bloom_prefix_sequences.sql.

Missing sequences:
- dat_instance_seq: For data category templates (prefix DAT)
- lm_instance_seq: For equipment category templates (prefix LM)
- hev_instance_seq: For health_event category templates (prefix HEV)

The trigger dynamically constructs sequence names as {lowercase_prefix}_instance_seq
and raises an exception if the sequence doesn't exist.

Revision ID: 0002_add_missing_euid_sequences
Revises: 0001_baseline
Create Date: 2025-02-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_add_missing_euid_sequences'
down_revision: Union[str, None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Sequences that need to be created
# Format: (sequence_name, comment)
MISSING_SEQUENCES = [
    ('dat_instance_seq', 'EUID sequence for data category templates (prefix DAT)'),
    ('lm_instance_seq', 'EUID sequence for equipment category templates (prefix LM)'),
    ('hev_instance_seq', 'EUID sequence for health_event category templates (prefix HEV)'),
]


def upgrade() -> None:
    """
    Create missing EUID sequences for template prefixes.
    
    Uses CREATE SEQUENCE IF NOT EXISTS for idempotency - safe to run
    multiple times or on databases where sequences already exist.
    """
    conn = op.get_bind()
    
    for seq_name, comment in MISSING_SEQUENCES:
        # Create sequence if it doesn't exist (idempotent)
        conn.execute(sa.text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1"))
        
        # Add comment to document purpose
        conn.execute(sa.text(f"COMMENT ON SEQUENCE {seq_name} IS :comment"), {"comment": comment})
        
        print(f"  ✓ Created sequence: {seq_name}")
    
    # Verify all required sequences now exist
    result = conn.execute(sa.text("""
        SELECT sequence_name 
        FROM information_schema.sequences 
        WHERE sequence_schema = 'public'
        AND sequence_name IN ('dat_instance_seq', 'lm_instance_seq', 'hev_instance_seq')
    """))
    
    created = [row[0] for row in result]
    expected = {'dat_instance_seq', 'lm_instance_seq', 'hev_instance_seq'}
    
    if set(created) != expected:
        missing = expected - set(created)
        raise RuntimeError(f"Migration failed: sequences not created: {missing}")
    
    print(f"EUID sequences migration complete. Created: {created}")


def downgrade() -> None:
    """
    Remove the EUID sequences added by this migration.
    
    WARNING: This will fail if any instances exist that use these sequences.
    Only run this if you're sure no data depends on these sequences.
    """
    conn = op.get_bind()
    
    for seq_name, _ in MISSING_SEQUENCES:
        # Check if sequence is in use (has been incremented)
        result = conn.execute(sa.text(f"SELECT last_value FROM {seq_name}"))
        last_value = result.scalar()
        
        if last_value > 1:
            print(f"  ⚠ Sequence {seq_name} has been used (last_value={last_value})")
            print(f"    Instances may exist with EUIDs from this sequence.")
        
        conn.execute(sa.text(f"DROP SEQUENCE IF EXISTS {seq_name}"))
        print(f"  ✓ Dropped sequence: {seq_name}")

