"""moderation_log target_kind += profile_city

Свободный ввод города теперь модерируется (check_text), и лог пишется с
target_kind='profile_city'. Старый CHECK его не разрешал → CheckViolationError
ронял транзакцию и регистрация застревала на шаге города. Расширяем CHECK.

Revision ID: a1c9e6f3b2d8
Revises: f4b8c2d9e7a1
Create Date: 2026-06-11
"""

from __future__ import annotations

from alembic import op

revision: str = "a1c9e6f3b2d8"
down_revision: str | None = "f4b8c2d9e7a1"
branch_labels: str | None = None
depends_on: str | None = None

_NAME = "ck_content_moderation_log_target_kind_allowed"

_OLD = (
    "target_kind IN ('profile_bio', 'profile_nickname', 'profile_media', "
    "'like_message', 'creator_post_text', 'creator_post_photo', "
    "'complaint_comment', 'feed_post', 'feed_comment', 'feed_media')"
)
_NEW = (
    "target_kind IN ('profile_bio', 'profile_nickname', 'profile_media', "
    "'like_message', 'creator_post_text', 'creator_post_photo', "
    "'complaint_comment', 'feed_post', 'feed_comment', 'feed_media', "
    "'profile_city')"
)


def upgrade() -> None:
    op.execute(f"ALTER TABLE content_moderation_log DROP CONSTRAINT {_NAME}")
    op.execute(f"ALTER TABLE content_moderation_log ADD CONSTRAINT {_NAME} CHECK ({_NEW})")


def downgrade() -> None:
    # Подчищаем строки с новым kind, иначе старый CHECK не наложится.
    op.execute("DELETE FROM content_moderation_log WHERE target_kind = 'profile_city'")
    op.execute(f"ALTER TABLE content_moderation_log DROP CONSTRAINT {_NAME}")
    op.execute(f"ALTER TABLE content_moderation_log ADD CONSTRAINT {_NAME} CHECK ({_OLD})")
