"""add api method v2

Revision ID: 20231231_add_api_method_v2
Revises: 20231230_add_task_type_check
Create Date: 2023-12-31 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '20231231_add_api_method_v2'
down_revision = '20231230_add_task_type_check'
branch_labels = None
depends_on = None

def upgrade():
    # Get inspector to check existing columns
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    columns = [col['name'] for col in inspector.get_columns('actions')]
    
    # Only add column if it doesn't exist
    if 'api_method' not in columns:
        op.add_column('actions', sa.Column('api_method', sa.String(), nullable=False, server_default='graphql'))
        
        # Add check constraint for valid api methods
        op.create_check_constraint(
            'ck_actions_api_method',
            'actions',
            sa.text("api_method IN ('graphql', 'rest')")
        )

def downgrade():
    # Try to remove constraint first
    try:
        op.drop_constraint('ck_actions_api_method', 'actions', type_='check')
    except:
        pass
    
    # Then try to remove column
    try:
        op.drop_column('actions', 'api_method')
    except:
        pass
