"""feed_target_kind_moderation_log

Расширяет CHECK content_moderation_log.target_kind значениями feed_post и
feed_comment — модерация текста постов и комментариев Ленты пишет лог с
этими target_kind.

Revision ID: c7f1a9b3e2d4
Revises: 5a087be4b5f3
Create Date: 2026-05-17
"""

from __future__ import annotations

from alembic import op

revision = "c7f1a9b3e2d4"
down_revision = "5a087be4b5f3"
branch_labels = None
depends_on = None

# Имя констрейнта в БД (с naming_convention-префиксом ck_<table>_).
_NAME = "ck_content_moderation_log_target_kind_allowed"

_OLD = (
    "target_kind IN ('profile_bio', 'profile_nickname', 'profile_media', "
    "'like_message', 'creator_post_text', 'creator_post_photo', "
    "'complaint_comment')"
)
_NEW = (
    "target_kind IN ('profile_bio', 'profile_nickname', 'profile_media', "
    "'like_message', 'creator_post_text', 'creator_post_photo', "
    "'complaint_comment', 'feed_post', 'feed_comment', 'feed_media')"
)


def upgrade() -> None:
    op.execute(f"ALTER TABLE content_moderation_log DROP CONSTRAINT {_NAME}")
    op.execute(f"ALTER TABLE content_moderation_log ADD CONSTRAINT {_NAME} CHECK ({_NEW})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE content_moderation_log DROP CONSTRAINT {_NAME}")
    op.execute(f"ALTER TABLE content_moderation_log ADD CONSTRAINT {_NAME} CHECK ({_OLD})")
