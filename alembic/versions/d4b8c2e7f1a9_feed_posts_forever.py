"""feed posts forever: feed_post_ttl_hours 48→0, активным постам expires_at=NULL

Пакет-2 цикла уведомлений (запрос клиента): убрать ограничение по времени
у постов Ленты. Механизм TTL остаётся: значение >0 в feed_post_ttl_hours
возвращает экспирацию для НОВЫХ постов (правится через скрытую панель
настроек или нами руками).

Активным постам обнуляем expires_at — они становятся вечными. Уже истёкшие
(status='expired') НЕ воскрешаем: purge мог удалить соседние, восстановилось
бы случайное окно последних дней.

Revision ID: d4b8c2e7f1a9
Revises: c7e9a1b4d3f8
Create Date: 2026-07-14 12:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d4b8c2e7f1a9"
down_revision: str | None = "c7e9a1b4d3f8"
branch_labels: str | None = None
depends_on: str | None = None


TTL_KEY = "feed_post_ttl_hours"
TTL_FOREVER = "0"
TTL_OLD_VALUE = "48"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE app_settings SET value = :value WHERE key = :key"),
        {"key": TTL_KEY, "value": TTL_FOREVER},
    )
    bind.execute(
        sa.text("UPDATE feed_posts SET expires_at = NULL WHERE status = 'active'")
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE app_settings SET value = :value WHERE key = :key"),
        {"key": TTL_KEY, "value": TTL_OLD_VALUE},
    )
    # Вечным активным постам возвращаем таймер от created_at (как было бы при 48ч).
    bind.execute(
        sa.text(
            "UPDATE feed_posts SET expires_at = created_at + interval '48 hours' "
            "WHERE status = 'active' AND expires_at IS NULL"
        )
    )
