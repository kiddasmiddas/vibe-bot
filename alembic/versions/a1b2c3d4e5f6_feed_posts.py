"""feed_posts

Revision ID: a1b2c3d4e5f6
Revises: 36cb6e03a0d0
Create Date: 2026-05-16 00:00:00.000000

Таблицы feed_posts и feed_post_media для фичи «Лента».
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "36cb6e03a0d0"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "feed_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("author_name", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_feed_posts_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_posts")),
    )
    op.create_index(
        "ix_feed_posts_status_published_at",
        "feed_posts",
        ["status", "published_at"],
        unique=False,
    )

    op.create_table(
        "feed_post_media",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("file_id", sa.String(length=256), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["feed_posts.id"],
            name=op.f("fk_feed_post_media_post_id_feed_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_post_media")),
    )
    op.create_index(
        "ix_feed_post_media_post_id_position",
        "feed_post_media",
        ["post_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_feed_post_media_post_id_position", table_name="feed_post_media")
    op.drop_table("feed_post_media")
    op.drop_index("ix_feed_posts_status_published_at", table_name="feed_posts")
    op.drop_table("feed_posts")
