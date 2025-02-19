"""add_unique_constraint_to_account_login

Revision ID: 0118ea714288
Revises: 09788834af29
Create Date: 2025-02-18 23:06:50.659751

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0118ea714288'
down_revision: Union[str, None] = '09788834af29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from sqlalchemy import inspect

def upgrade() -> None:
    # Get inspector to check existing constraints
    conn = op.get_bind()
    insp = inspect(conn)
    
    # Check if unique constraint exists
    existing_constraints = insp.get_unique_constraints('accounts')
    if not any(c['name'] == 'uq_accounts_login' for c in existing_constraints):
        # Create unique constraint if it doesn't exist
        op.create_unique_constraint('uq_accounts_login', 'accounts', ['login'])

    # Check if index exists
    existing_indexes = insp.get_indexes('accounts')
    if not any(i['name'] == 'ix_accounts_login' for i in existing_indexes):
        # Create index if it doesn't exist
        op.create_index('ix_accounts_login', 'accounts', ['login'])


def downgrade() -> None:
    try:
        # Try to drop unique constraint
        op.drop_constraint('uq_accounts_login', 'accounts', type_='unique')
    except:
        pass  # Ignore if constraint doesn't exist
        
    try:
        # Try to drop index
        op.drop_index('ix_accounts_login', table_name='accounts')
    except:
        pass  # Ignore if index doesn't exist
