"""min_age default lowered from 18 to 14

Идемпотентно понижает app_settings.min_age до 14 для уже задеплоенных систем,
где seed-миграция d96deed7e5da проставила 18.

Revision ID: c4d8e7a2f9b1
Revises: b7e2c4f9a8d3
Create Date: 2026-06-04 18:25:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e7a2f9b1"
down_revision: str | None = "b7e2c4f9a8d3"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Понижаем минимальный возраст регистрации с 18 до 14, но только если в БД
    # лежит исходный seed-дефолт. Если админ уже руками менял (например, через
    # /admin → Настройки), его значение не трогаем.
    op.execute(
        sa.text(
            "UPDATE app_settings SET value = '14' "
            "WHERE key = 'min_age' AND value = '18'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE app_settings SET value = '18' "
            "WHERE key = 'min_age' AND value = '14'"
        )
    )
