"""seed feed_post_limit_regular_month setting

Открываем создание постов в Ленте обычным пользователям (раньше — только
Premium). Лимит для непремиума: 5 постов в календарный месяц. Значение
вынесено в `app_settings`, чтобы заказчик мог менять его из /admin без
деплоя (рядом с feed_post_limit_premium_month=50 для Premium).

Идемпотентно (ON CONFLICT DO NOTHING): повторный upgrade не ломается,
ручная правка значения в админке не затирается.

Revision ID: e7d2b9a4c1f6
Revises: a1c9e6f3b2d8
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "e7d2b9a4c1f6"
down_revision: str | None = "a1c9e6f3b2d8"
branch_labels: str | None = None
depends_on: str | None = None


SETTING_KEY = "feed_post_limit_regular_month"
SETTING_VALUE = "5"
SETTING_DESCRIPTION = (
    "Месячный лимит постов в Ленте для обычных пользователей "
    "(Premium — feed_post_limit_premium_month)"
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO app_settings (key, value, description) "
            "VALUES (:key, :value, :description) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"key": SETTING_KEY, "value": SETTING_VALUE, "description": SETTING_DESCRIPTION},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM app_settings WHERE key = :key"),
        {"key": SETTING_KEY},
    )
