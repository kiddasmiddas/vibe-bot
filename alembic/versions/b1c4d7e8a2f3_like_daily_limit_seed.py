"""seed like_daily_limit setting

Добавляет продуктовую настройку `like_daily_limit=30` в `app_settings`.
Используется матчинг-сервисом: обычные пользователи могут поставить не
более N лайков (включая суперлайки) в сутки; Premium-доступ снимает лимит.

Миграция идемпотентна (ON CONFLICT DO NOTHING): повторный upgrade не
ломается, ручная правка значения в админке не затирается.

Revision ID: b1c4d7e8a2f3
Revises: a3f2c8d4e9b6
Create Date: 2026-06-08 18:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b1c4d7e8a2f3"
down_revision: str | None = "a3f2c8d4e9b6"
branch_labels: str | None = None
depends_on: str | None = None


SETTING_KEY = "like_daily_limit"
SETTING_VALUE = "30"
SETTING_DESCRIPTION = "Дневной лимит лайков для обычных пользователей (Premium снимает лимит)"


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
