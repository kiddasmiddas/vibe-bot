"""feed_comments_reactions_restrictions

Revision ID: efeca2a5e29f
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16 21:52:07.198677

Добавляет таблицы feed_comments, feed_reactions, feed_comment_restrictions
и колонку is_pending_review к feed_posts.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "efeca2a5e29f"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Добавляем is_pending_review к feed_posts.
    op.add_column(
        "feed_posts",
        sa.Column(
            "is_pending_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Таблица комментариев.
    op.create_table(
        "feed_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("media_type", sa.String(length=16), nullable=True),
        sa.Column("media_file_id", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "text IS NOT NULL OR (media_type IS NOT NULL AND media_file_id IS NOT NULL)",
            name="feed_comment_text_or_media",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_feed_comments_author_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["feed_posts.id"],
            name=op.f("fk_feed_comments_post_id_feed_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_comments")),
    )
    op.create_index(
        "ix_feed_comments_post_id_created_at",
        "feed_comments",
        ["post_id", "created_at"],
        unique=False,
    )

    # Таблица реакций — составной PK (post_id, user_id).
    op.create_table(
        "feed_reactions",
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reaction_type", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["feed_posts.id"],
            name=op.f("fk_feed_reactions_post_id_feed_posts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_feed_reactions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("post_id", "user_id", name=op.f("pk_feed_reactions")),
    )

    # Таблица ограничений в комментариях — PK user_id.
    op.create_table(
        "feed_comment_restrictions",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"],
            ["users.id"],
            name=op.f("fk_feed_comment_restrictions_created_by_admin_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_feed_comment_restrictions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_feed_comment_restrictions")),
    )


def downgrade() -> None:
    op.drop_table("feed_comment_restrictions")
    op.drop_table("feed_reactions")
    op.drop_index("ix_feed_comments_post_id_created_at", table_name="feed_comments")
    op.drop_table("feed_comments")
    op.drop_column("feed_posts", "is_pending_review")
