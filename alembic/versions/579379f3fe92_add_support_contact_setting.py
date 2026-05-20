"""add_support_contact_setting

Revision ID: 579379f3fe92
Revises: 83faedaaca90
Create Date: 2026-05-13 15:55:41.585057

Добавляет ключ `support_contact` в `app_settings` — контакт поддержки для
кнопки «Поддержка / правила». Значение пустое: админ задаёт его через
админ-режим. Если пусто — хэндлер отдаёт fallback-строку.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "579379f3fe92"
down_revision: str | None = "83faedaaca90"
branch_labels: str | None = None
depends_on: str | None = None


_app_settings_table = sa.table(
    "app_settings",
    sa.column("key", sa.String),
    sa.column("value", sa.Text),
    sa.column("description", sa.Text),
)

_SUPPORT_CONTACT_KEY = "support_contact"


def upgrade() -> None:
    op.bulk_insert(
        _app_settings_table,
        [
            {
                "key": _SUPPORT_CONTACT_KEY,
                "value": "",
                "description": "Контакт поддержки для меню «Поддержка / правила»",
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM app_settings WHERE key = :key").bindparams(
            key=_SUPPORT_CONTACT_KEY
        )
    )
