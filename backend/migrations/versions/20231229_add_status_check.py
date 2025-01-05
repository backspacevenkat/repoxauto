"""add_status_check

Revision ID: 20231229_add_status_check
Revises: 20231228_add_action_type_check
Create Date: 2024-12-29 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic
revision = '20231229_add_status_check'
down_revision = '20231228_add_action_type_check'
branch_labels = None
depends_on = None

def upgrade():
    # Add check constraint for status
    # SQLite doesn't support ALTER TABLE ADD CONSTRAINT, so we need to:
    # 1. Create new table with constraint
    # 2. Copy data
    # 3. Drop old table
    # 4. Rename new table
    
    conn = op.get_bind()
    
    # Create new table with both constraints
    conn.execute(text("""
        CREATE TABLE actions_new (
            id INTEGER PRIMARY KEY,
            account_id INTEGER REFERENCES accounts(id),
            task_id INTEGER REFERENCES tasks(id),
            action_type TEXT NOT NULL CHECK (
                action_type IN (
                    'like_tweet', 'retweet_tweet', 'reply_tweet', 
                    'quote_tweet', 'create_tweet'
                )
            ),
            tweet_url TEXT,
            tweet_id TEXT,
            status TEXT DEFAULT 'pending' CHECK (
                status IN (
                    'pending', 'running', 'completed', 'failed', 
                    'cancelled', 'locked'
                )
            ),
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            executed_at TIMESTAMP,
            rate_limit_reset TIMESTAMP,
            rate_limit_remaining INTEGER,
            meta_data JSON
        )
    """))
    
    # Copy data, ensuring only valid statuses
    conn.execute(text("""
        INSERT INTO actions_new 
        SELECT * FROM actions 
        WHERE status IN (
            'pending', 'running', 'completed', 'failed', 
            'cancelled', 'locked'
        )
    """))
    
    # Drop old table
    conn.execute(text("DROP TABLE actions"))
    
    # Rename new table
    conn.execute(text("ALTER TABLE actions_new RENAME TO actions"))
    
    # Recreate indexes
    conn.execute(text("""
        CREATE UNIQUE INDEX uq_account_action_tweet 
        ON actions (account_id, action_type, tweet_id) 
        WHERE status IN ('pending', 'running', 'locked')
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_action_status 
        ON actions (status)
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_account_action_created 
        ON actions (account_id, action_type, created_at)
    """))

def downgrade():
    # Remove status check constraint by recreating table without it
    conn = op.get_bind()
    
    # Create new table with only action_type constraint
    conn.execute(text("""
        CREATE TABLE actions_new (
            id INTEGER PRIMARY KEY,
            account_id INTEGER REFERENCES accounts(id),
            task_id INTEGER REFERENCES tasks(id),
            action_type TEXT NOT NULL CHECK (
                action_type IN (
                    'like_tweet', 'retweet_tweet', 'reply_tweet', 
                    'quote_tweet', 'create_tweet'
                )
            ),
            tweet_url TEXT,
            tweet_id TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            executed_at TIMESTAMP,
            rate_limit_reset TIMESTAMP,
            rate_limit_remaining INTEGER,
            meta_data JSON
        )
    """))
    
    # Copy all data
    conn.execute(text("INSERT INTO actions_new SELECT * FROM actions"))
    
    # Drop old table
    conn.execute(text("DROP TABLE actions"))
    
    # Rename new table
    conn.execute(text("ALTER TABLE actions_new RENAME TO actions"))
    
    # Recreate indexes
    conn.execute(text("""
        CREATE UNIQUE INDEX uq_account_action_tweet 
        ON actions (account_id, action_type, tweet_id) 
        WHERE status IN ('pending', 'running', 'locked')
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_action_status 
        ON actions (status)
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_account_action_created 
        ON actions (account_id, action_type, created_at)
    """))
