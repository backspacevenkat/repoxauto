"""create_system_settings_table

Revision ID: 8aa2ba4de389
Revises: 0118ea714288
Create Date: 2025-02-18 23:18:46.840502

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8aa2ba4de389'
down_revision: Union[str, None] = '0118ea714288'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
