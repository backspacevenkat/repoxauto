"""add system settings

Revision ID: 09788834af29
Revises: 
Create Date: 2025-02-17 19:50:22.328258

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = '09788834af29'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create system_settings table
    op.create_table('system_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('max_concurrent_workers', sa.Integer(), nullable=True),
        sa.Column('max_requests_per_worker', sa.Integer(), nullable=True),
        sa.Column('request_interval', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Insert default settings
    op.execute("""
        INSERT INTO system_settings (max_concurrent_workers, max_requests_per_worker, request_interval)
        VALUES (12, 900, 60)
    """)


def downgrade() -> None:
    # Drop system_settings table
    op.drop_table('system_settings')
