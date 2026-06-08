"""premium_tariffs_seed

Revision ID: f9a3b7c2e4d1
Revises: a3f2c8d4e9b6
Create Date: 2026-06-08 18:35:00.000000

Заполняет таблицу app_settings новыми ключами тарифов Premium:
  * premium_price_week_rub        = 100
  * premium_duration_days_week    = 7
  * premium_price_month_rub       = 200
  * premium_duration_days_month   = 30
  * premium_price_year_rub        = 1500
  * premium_duration_days_year    = 365

Идемпотентна (ON CONFLICT DO UPDATE по ключу).

Старые ключи premium_price_rub и premium_duration_days НЕ удаляются —
оставляем как fallback для месячного тарифа (см. PaymentService._get_price_and_duration).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "f9a3b7c2e4d1"
down_revision: str | None = "a3f2c8d4e9b6"
branch_labels: str | None = None
depends_on: str | None = None


PREMIUM_TARIFF_SETTINGS: list[tuple[str, str, str]] = [
    ("premium_price_week_rub", "100", "Цена Premium на 7 дней, ₽"),
    ("premium_duration_days_week", "7", "Длительность недельного тарифа Premium, дни"),
    ("premium_price_month_rub", "200", "Цена Premium на 30 дней, ₽"),
    ("premium_duration_days_month", "30", "Длительность месячного тарифа Premium, дни"),
    ("premium_price_year_rub", "1500", "Цена Premium на 365 дней, ₽"),
    ("premium_duration_days_year", "365", "Длительность годового тарифа Premium, дни"),
]


def upgrade() -> None:
    bind = op.get_bind()
    # Идемпотентный upsert: если ключ уже существует — обновим value/description.
    for key, value, description in PREMIUM_TARIFF_SETTINGS:
        bind.execute(
            sa.text(
                """
                INSERT INTO app_settings (key, value, description)
                VALUES (:key, :value, :description)
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value,
                    description = EXCLUDED.description
                """
            ),
            {"key": key, "value": value, "description": description},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM app_settings WHERE key = ANY(:keys)"),
        {"keys": [k for k, _, _ in PREMIUM_TARIFF_SETTINGS]},
    )
