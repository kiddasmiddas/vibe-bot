"""seed profile limits: fandoms_max_selected=15, bio_max_length 500→200

Пакет-2 цикла уведомлений (запрос клиента): максимум 15 фандомов («свои»
и «ищу») и «О себе» до 200 символов, чтобы карточка анкеты влезала в лимит
Telegram-caption 1024. Оба значения правятся в /admin → ⚙️ Настройки →
📏 Лимиты анкеты.

`fandoms_max_selected` — новый ключ (ON CONFLICT DO NOTHING, идемпотентно).
`bio_max_length` уже существует (сид d96deed7e5da, 500) — обновляем значение;
клиент раздел настроек ещё не видел, ручных правок ключа не было.

Revision ID: c7e9a1b4d3f8
Revises: a8d4f2c7b9e1
Create Date: 2026-07-14 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c7e9a1b4d3f8"
down_revision: str | None = "a8d4f2c7b9e1"
branch_labels: str | None = None
depends_on: str | None = None


FANDOMS_KEY = "fandoms_max_selected"
FANDOMS_VALUE = "15"
FANDOMS_DESCRIPTION = "Максимум выбранных фандомов в анкете (и «свои», и «ищу»)"

BIO_KEY = "bio_max_length"
BIO_NEW_VALUE = "200"
BIO_OLD_VALUE = "500"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO app_settings (key, value, description) "
            "VALUES (:key, :value, :description) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"key": FANDOMS_KEY, "value": FANDOMS_VALUE, "description": FANDOMS_DESCRIPTION},
    )
    bind.execute(
        sa.text("UPDATE app_settings SET value = :value WHERE key = :key"),
        {"key": BIO_KEY, "value": BIO_NEW_VALUE},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM app_settings WHERE key = :key"),
        {"key": FANDOMS_KEY},
    )
    bind.execute(
        sa.text("UPDATE app_settings SET value = :value WHERE key = :key"),
        {"key": BIO_KEY, "value": BIO_OLD_VALUE},
    )
