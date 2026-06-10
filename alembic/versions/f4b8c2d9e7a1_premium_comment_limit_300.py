"""feed_comment_limit_premium_day 100 → 300 (по ТЗ заказчика)

Описание Premium обещает «300 комментариев в Ленте в день» — выравниваем
настройку с текстом. Идемпотентно: трогаем только значение '100'.

Revision ID: f4b8c2d9e7a1
Revises: d7e3f9c1a5b8
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "f4b8c2d9e7a1"
down_revision: str | None = "d7e3f9c1a5b8"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE app_settings SET value = '300', updated_at = now() "
        "WHERE key = 'feed_comment_limit_premium_day' AND value = '100'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE app_settings SET value = '100', updated_at = now() "
        "WHERE key = 'feed_comment_limit_premium_day' AND value = '300'"
    )
