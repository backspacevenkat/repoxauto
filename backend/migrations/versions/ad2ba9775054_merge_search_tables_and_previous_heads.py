"""merge_search_tables_and_previous_heads

Revision ID: ad2ba9775054
Revises: 20240124_add_search_tables, 3c9f329ff471
Create Date: 2024-12-27 16:28:45.208299

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = 'ad2ba9775054'
down_revision = ('20240124_add_search_tables', '3c9f329ff471')
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass