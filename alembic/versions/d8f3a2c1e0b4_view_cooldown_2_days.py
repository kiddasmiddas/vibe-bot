"""view_cooldown_2_days

Revision ID: d8f3a2c1e0b4
Revises: c7f1a9b3e2d4
Create Date: 2026-05-17 13:35:00.000000

Уменьшаем view_cooldown_days с 14 до 2: скипнутая («отложенная») анкета
возвращается в выдачу мэтчинга через 2 дня, а не через 2 недели. Лайк и
дизлайк исключают анкету навсегда — на них этот срок не влияет.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d8f3a2c1e0b4"
down_revision: str | None = "c7f1a9b3e2d4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE app_settings SET value = '2' WHERE key = 'view_cooldown_days'"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE app_settings SET value = '14' WHERE key = 'view_cooldown_days'"))
