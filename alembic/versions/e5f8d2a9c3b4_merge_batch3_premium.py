"""merge_batch3_premium

Объединяет три параллельные seed/DDL-миграции батча 3 (Premium-bundle),
все три ответвлены от общего парента a3f2c8d4e9b6:
- b1c4d7e8a2f3 (like_daily_limit_seed)
- c2d8f1a4b5e7 (vibe_by_photo_requests)
- f9a3b7c2e4d1 (premium_tariffs_seed)

Конфликтов нет — все три аддитивные и не пересекаются ни по таблицам,
ни по ключам app_settings. Merge-узел нужен только чтобы у alembic
была единственная голова.

Revision ID: e5f8d2a9c3b4
Revises: b1c4d7e8a2f3, c2d8f1a4b5e7, f9a3b7c2e4d1
Create Date: 2026-06-08 21:00:00.000000
"""

from __future__ import annotations

revision: str = "e5f8d2a9c3b4"
down_revision: tuple[str, ...] = (
    "b1c4d7e8a2f3",
    "c2d8f1a4b5e7",
    "f9a3b7c2e4d1",
)
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
