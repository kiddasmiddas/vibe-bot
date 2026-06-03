"""feed_post_updated_at

Revision ID: b7e2c4f9a8d3
Revises: 8121a079ffae
Create Date: 2026-06-03 00:00:00.000000

Добавляет поле updated_at в feed_posts (Волна 3 — редактирование постов Ленты).

Для существующих записей updated_at инициализируется значением created_at,
для новых записей server_default = now() и явное обновление в FeedService.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b7e2c4f9a8d3"
down_revision: str | None = "8121a079ffae"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "feed_posts",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Для существующих постов выравниваем updated_at с created_at,
    # чтобы не выглядело так, будто все посты «отредактированы» только что.
    op.execute("UPDATE feed_posts SET updated_at = created_at")


def downgrade() -> None:
    op.drop_column("feed_posts", "updated_at")
