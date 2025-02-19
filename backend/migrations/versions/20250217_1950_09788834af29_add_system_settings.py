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
    sa.Column('account_id', sa.INTEGER(), nullable=True),
    sa.Column('follow_list_id', sa.INTEGER(), nullable=True),
    sa.Column('status', sa.VARCHAR(), nullable=True),
    sa.Column('started_at', sa.DATETIME(), nullable=True),
    sa.Column('followed_at', sa.DATETIME(), nullable=True),
    sa.Column('scheduled_for', sa.DATETIME(), nullable=True),
    sa.Column('error_message', sa.VARCHAR(), nullable=True),
    sa.Column('meta_data', sa.VARCHAR(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=True),
    sa.Column('updated_at', sa.DATETIME(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
    sa.ForeignKeyConstraint(['follow_list_id'], ['follow_lists.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('follow_settings',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), nullable=True),
    sa.Column('max_follows_per_day', sa.INTEGER(), nullable=True),
    sa.Column('max_follows_per_interval', sa.INTEGER(), nullable=True),
    sa.Column('min_following', sa.INTEGER(), nullable=True),
    sa.Column('max_following', sa.INTEGER(), nullable=True),
    sa.Column('interval_minutes', sa.INTEGER(), nullable=True),
    sa.Column('schedule_groups', sa.INTEGER(), nullable=True),
    sa.Column('schedule_hours', sa.INTEGER(), nullable=True),
    sa.Column('internal_ratio', sa.INTEGER(), nullable=True),
    sa.Column('external_ratio', sa.INTEGER(), nullable=True),
    sa.Column('last_active', sa.DATETIME(), nullable=True),
    sa.Column('meta_data', sqlite.JSON(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=True),
    sa.Column('updated_at', sa.DATETIME(), nullable=True),
    sa.Column('last_updated', sa.DATETIME(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_follow_settings_id', 'follow_settings', ['id'], unique=False)
    op.create_table('follow_lists',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('list_type', sa.VARCHAR(length=8), nullable=False),
    sa.Column('username', sa.VARCHAR(), nullable=False),
    sa.Column('account_login', sa.VARCHAR(), nullable=True),
    sa.Column('uploaded_by', sa.INTEGER(), nullable=False),
    sa.Column('status', sa.VARCHAR(), nullable=False),
    sa.Column('created_at', sa.DATETIME(), nullable=True),
    sa.Column('updated_at', sa.DATETIME(), nullable=True),
    sa.Column('validated_at', sa.DATETIME(), nullable=True),
    sa.Column('meta_data', sa.VARCHAR(), nullable=True),
    sa.ForeignKeyConstraint(['account_login'], ['accounts.login'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_follow_lists_username', 'follow_lists', ['username'], unique=False)
    # ### end Alembic commands ###
