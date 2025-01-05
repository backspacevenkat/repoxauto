"""add_action_constraints

Revision ID: df75ff415606
Revises: 20231227_make_tweet_url_nullable
Create Date: 2024-12-27 22:34:02.672421

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic
revision = 'df75ff415606'
down_revision = '20231227_make_tweet_url_nullable'
branch_labels = None
depends_on = None

def upgrade():
    # SQLite helper to check if index exists
    def index_exists(index_name):
        conn = op.get_bind()
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name=:name"),
            {"name": index_name}
        ).fetchone()
        return bool(result)

    conn = op.get_bind()
    
    # Create unique index with ON CONFLICT IGNORE
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_account_action_tweet 
        ON actions (account_id, action_type, tweet_id) 
        WHERE status IN ('pending', 'running', 'locked')
    """))
    
    # Create other indexes
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_action_status 
        ON actions (status)
    """))
    
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_account_action_created 
        ON actions (account_id, action_type, created_at)
    """))

def downgrade():
    conn = op.get_bind()
    
    # Drop indexes
    conn.execute(text("DROP INDEX IF EXISTS uq_account_action_tweet"))
    conn.execute(text("DROP INDEX IF EXISTS idx_action_status"))
    conn.execute(text("DROP INDEX IF EXISTS idx_account_action_created"))
