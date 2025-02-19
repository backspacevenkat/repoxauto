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


def upgrade() -> None:
    # Create unique index for login column
    op.create_unique_constraint('uq_accounts_login', 'accounts', ['login'])
    # Create index for better query performance
    op.create_index('ix_accounts_login', 'accounts', ['login'])


def downgrade() -> None:
    # Drop unique constraint and index
    op.drop_constraint('uq_accounts_login', 'accounts', type_='unique')
    op.drop_index('ix_accounts_login', table_name='accounts')
