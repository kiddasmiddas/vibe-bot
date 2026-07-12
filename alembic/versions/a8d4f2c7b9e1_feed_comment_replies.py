"""Ветки комментариев Ленты: parent_comment_id (глубина 1).

У ответа parent_comment_id всегда указывает на корневой комментарий поста —
глубину 1 гарантирует сервис (ответ на ответ прикрепляется к тому же корню).

Revision ID: a8d4f2c7b9e1
Revises: f1a7c3e9d2b5
Create Date: 2026-07-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a8d4f2c7b9e1"
down_revision = "f1a7c3e9d2b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feed_comments",
        sa.Column("parent_comment_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_feed_comments_parent_comment_id",
        "feed_comments",
        "feed_comments",
        ["parent_comment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_feed_comments_parent_comment_id",
        "feed_comments",
        ["parent_comment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_feed_comments_parent_comment_id", table_name="feed_comments")
    op.drop_constraint(
        "fk_feed_comments_parent_comment_id", "feed_comments", type_="foreignkey"
    )
    op.drop_column("feed_comments", "parent_comment_id")
