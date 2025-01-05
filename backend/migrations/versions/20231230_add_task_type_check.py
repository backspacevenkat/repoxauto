"""add_task_type_check

Revision ID: 20231230_add_task_type_check
Revises: 20231229_add_status_check
Create Date: 2024-12-30 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic
revision = '20231230_add_task_type_check'
down_revision = '20231229_add_status_check'
branch_labels = None
depends_on = None

def upgrade():
    # Add check constraint for task type
    # SQLite doesn't support ALTER TABLE ADD CONSTRAINT, so we need to:
    # 1. Create new table with constraint
    # 2. Copy data
    # 3. Drop old table
    # 4. Rename new table
    
    conn = op.get_bind()
    
    # Create new table with constraint
    conn.execute(text("""
        CREATE TABLE tasks_new (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL CHECK (
                type IN (
                    'like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet',
                    'scrape_profile', 'scrape_tweets', 'search_trending', 'search_tweets', 'search_users',
                    'user_profile', 'user_tweets'
                )
            ),
            status TEXT DEFAULT 'pending',
            input_params JSON NOT NULL,
            result JSON,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            worker_account_id INTEGER REFERENCES accounts(id),
            priority INTEGER DEFAULT 0,
            retry_count INTEGER DEFAULT 0,
            execution_time FLOAT
        )
    """))
    
    # Copy data, but only valid task types
    conn.execute(text("""
        INSERT INTO tasks_new 
        SELECT * FROM tasks 
        WHERE type IN (
            'like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet',
            'scrape_profile', 'scrape_tweets', 'search_trending', 'search_tweets', 'search_users',
            'user_profile', 'user_tweets'
        )
    """))
    
    # Drop old table
    conn.execute(text("DROP TABLE tasks"))
    
    # Rename new table
    conn.execute(text("ALTER TABLE tasks_new RENAME TO tasks"))
    
    # Recreate indexes
    conn.execute(text("CREATE INDEX idx_tasks_type ON tasks (type)"))
    conn.execute(text("CREATE INDEX idx_tasks_status ON tasks (status)"))

def downgrade():
    # Remove check constraint by recreating table without it
    conn = op.get_bind()
    
    conn.execute(text("""
        CREATE TABLE tasks_new (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            input_params JSON NOT NULL,
            result JSON,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            worker_account_id INTEGER REFERENCES accounts(id),
            priority INTEGER DEFAULT 0,
            retry_count INTEGER DEFAULT 0,
            execution_time FLOAT
        )
    """))
    
    # Copy all data
    conn.execute(text("INSERT INTO tasks_new SELECT * FROM tasks"))
    
    # Drop old table
    conn.execute(text("DROP TABLE tasks"))
    
    # Rename new table
    conn.execute(text("ALTER TABLE tasks_new RENAME TO tasks"))
    
    # Recreate indexes
    conn.execute(text("CREATE INDEX idx_tasks_type ON tasks (type)"))
    conn.execute(text("CREATE INDEX idx_tasks_status ON tasks (status)"))
