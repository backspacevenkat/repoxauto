"""Make tweet_url nullable

Revision ID: 20231227_make_tweet_url_nullable
Revises: 8c895c17da5b
Create Date: 2023-12-27 19:54:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20231227_make_tweet_url_nullable'
down_revision: Union[str, None] = '8c895c17da5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create new table
    op.create_table('actions_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('task_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(), nullable=False),
        sa.Column('tweet_url', sa.String(), nullable=True),  # This is now nullable
        sa.Column('tweet_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('rate_limit_reset', sa.DateTime(), nullable=True),
        sa.Column('rate_limit_remaining', sa.Integer(), nullable=True),
        sa.Column('meta_data', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Copy data
    op.execute('INSERT INTO actions_new SELECT * FROM actions')
    
    # Drop old table
    op.drop_table('actions')
    
    # Rename new table
    op.rename_table('actions_new', 'actions')


def downgrade() -> None:
    # Create new table with non-nullable tweet_url
    op.create_table('actions_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('task_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(), nullable=False),
        sa.Column('tweet_url', sa.String(), nullable=False),  # Back to non-nullable
        sa.Column('tweet_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('rate_limit_reset', sa.DateTime(), nullable=True),
        sa.Column('rate_limit_remaining', sa.Integer(), nullable=True),
        sa.Column('meta_data', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Copy data (this might fail if there are null tweet_urls)
    op.execute('INSERT INTO actions_new SELECT * FROM actions')
    
    # Drop old table
    op.drop_table('actions')
    
    # Rename new table
    op.rename_table('actions_new', 'actions')
