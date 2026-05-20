"""seed_feed_settings

Revision ID: 5a087be4b5f3
Revises: efeca2a5e29f
Create Date: 2026-05-16 21:52:31.932886

Вставляет продуктовые настройки Ленты в app_settings.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "5a087be4b5f3"
down_revision: str | None = "efeca2a5e29f"
branch_labels: str | None = None
depends_on: str | None = None

app_settings_table = sa.table(
    "app_settings",
    sa.column("key", sa.String),
    sa.column("value", sa.Text),
    sa.column("description", sa.Text),
)

FEED_SETTINGS = [
    (
        "feed_post_limit_premium_month",
        "50",
        "Лимит постов в Ленте для Premium-пользователей в месяц (запас до 100)",
    ),
    (
        "feed_comment_limit_regular_day",
        "30",
        "Лимит комментариев в Ленте для обычного пользователя в день",
    ),
    (
        "feed_comment_limit_premium_day",
        "100",
        "Лимит комментариев в Ленте для Premium-пользователя в день (запас до 300)",
    ),
    (
        "feed_post_ttl_hours",
        "48",
        "Время жизни поста в Ленте, часов",
    ),
    (
        "feed_post_purge_days",
        "4",
        "Через сколько дней после истечения поста физически удалять его (purge_at = expires_at + N дней)",
    ),
    (
        "feed_preview_limit_no_profile",
        "10",
        "Сколько постов показывать гостю без заполненного профиля",
    ),
    (
        "feed_premoderate_first_n_posts",
        "3",
        "Первые N постов нового автора уходят на ручную проверку (0 = выкл)",
    ),
]


def upgrade() -> None:
    op.bulk_insert(
        app_settings_table,
        [{"key": k, "value": v, "description": d} for k, v, d in FEED_SETTINGS],
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM app_settings WHERE key = ANY(:keys)"),
        {"keys": [k for k, _, _ in FEED_SETTINGS]},
    )
