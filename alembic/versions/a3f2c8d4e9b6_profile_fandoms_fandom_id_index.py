"""index on profile_fandoms(fandom_id) for cascade desired_fandom_ids fallback

Composite PK на (profile_id, fandom_id) не помогает запросам с фильтром
только по fandom_id (SELECT profile_id FROM profile_fandoms WHERE fandom_id IN ...).
Без отдельного индекса PostgreSQL делает seq-scan; при росте таблицы это
вылезает в хот-пути матчинга (Stage 2/3 fallback). Добавляем secondary index.

Revision ID: a3f2c8d4e9b6
Revises: c4d8e7a2f9b1
Create Date: 2026-06-08 17:30:00.000000
"""

from __future__ import annotations

from alembic import op

revision: str = "a3f2c8d4e9b6"
down_revision: str | None = "c4d8e7a2f9b1"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_profile_fandoms_fandom_id",
        "profile_fandoms",
        ["fandom_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_fandoms_fandom_id", table_name="profile_fandoms")
