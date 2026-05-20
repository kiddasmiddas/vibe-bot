"""merge_matching_and_premium

Revision ID: ba3a3f9ad7cd
Revises: 614d0b5ecd93, a089a4efa0d2
Create Date: 2026-05-13 15:14:16.870394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ba3a3f9ad7cd'
down_revision: Union[str, Sequence[str], None] = ('614d0b5ecd93', 'a089a4efa0d2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
