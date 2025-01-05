"""add search tables

Revision ID: 20240124_add_search_tables
Revises: # Leave this empty, alembic will fill it
Create Date: 2024-01-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20240124_add_search_tables'
down_revision = None  # Leave this empty, alembic will fill it
branch_labels = None
depends_on = None

def upgrade():
    # Create trending_topics table
    op.create_table(
        'trending_topics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('tweet_volume', sa.Integer(), nullable=True),
        sa.Column('domain', sa.String(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_trending_topics_name'), 'trending_topics', ['name'], unique=False)

    # Create topic_tweets table
    op.create_table(
        'topic_tweets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('keyword', sa.String(), nullable=False),
        sa.Column('tweet_id', sa.String(), nullable=False),
        sa.Column('tweet_data', sa.JSON(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_topic_tweets_keyword'), 'topic_tweets', ['keyword'], unique=False)
    op.create_index(op.f('ix_topic_tweets_tweet_id'), 'topic_tweets', ['tweet_id'], unique=False)

    # Create searched_users table
    op.create_table(
        'searched_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('keyword', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('user_data', sa.JSON(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_searched_users_keyword'), 'searched_users', ['keyword'], unique=False)
    op.create_index(op.f('ix_searched_users_user_id'), 'searched_users', ['user_id'], unique=False)

def downgrade():
    # Drop tables in reverse order
    op.drop_table('searched_users')
    op.drop_table('topic_tweets')
    op.drop_table('trending_topics')
