"""ad_rotation_posts: пул авто-рекламы для ленты анкет + сид ads_rotation_every_n

Новая фича: после каждой N-й анкеты (N=ads_rotation_every_n, дефолт 10) не-премиум
пользователю показывается креатив из пула по кругу. Таблица управляется из /admin.

Revision ID: f1a7c3e9d2b5
Revises: e7d2b9a4c1f6
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "f1a7c3e9d2b5"
down_revision: str | None = "e7d2b9a4c1f6"
branch_labels: str | None = None
depends_on: str | None = None


SETTING_KEY = "ads_rotation_every_n"
SETTING_VALUE = "10"
SETTING_DESCRIPTION = (
    "После скольких просмотренных анкет показывать авто-рекламу не-премиум пользователю"
)


def upgrade() -> None:
    op.create_table(
        "ad_rotation_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("media_file_id", sa.String(length=256), nullable=True),
        sa.Column("media_type", sa.String(length=16), nullable=True),
        sa.Column("button_label", sa.String(length=64), nullable=True),
        sa.Column("button_target", sa.String(length=16), nullable=True),
        sa.Column("button_url", sa.Text(), nullable=True),
        sa.Column("shown_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "media_type IS NULL OR media_type IN ('photo', 'video', 'animation')",
            name="ad_rotation_media_type_allowed",
        ),
        sa.CheckConstraint(
            "button_target IS NULL OR button_target IN ('url', 'premium')",
            name="ad_rotation_button_target_allowed",
        ),
        sa.CheckConstraint(
            "button_target IS DISTINCT FROM 'url' OR button_url IS NOT NULL",
            name="ad_rotation_url_target_needs_url",
        ),
        sa.CheckConstraint(
            "text IS NOT NULL OR media_file_id IS NOT NULL",
            name="ad_rotation_text_or_media",
        ),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Индекс под round-robin выбор (по last_shown_at, NULLs первыми) и пагинацию.
    op.create_index(
        "ix_ad_rotation_posts_rotation",
        "ad_rotation_posts",
        ["last_shown_at", "id"],
    )
    # Сид настройки частоты показа (идемпотентно).
    op.get_bind().execute(
        sa.text(
            "INSERT INTO app_settings (key, value, description) "
            "VALUES (:key, :value, :description) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"key": SETTING_KEY, "value": SETTING_VALUE, "description": SETTING_DESCRIPTION},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM app_settings WHERE key = :key"),
        {"key": SETTING_KEY},
    )
    op.drop_index("ix_ad_rotation_posts_rotation", table_name="ad_rotation_posts")
    op.drop_table("ad_rotation_posts")
