"""profiles.own_vibe_id nullable — вайб может ждать модератора

Premium-фича «Вайб по фото»: пользователь завершает регистрацию, не выбрав
вайб сам, и ждёт назначения модератором. До назначения own_vibe_id IS NULL;
такие анкеты исключаются из выдачи матчинга, вход в поиск закрыт гардом.

Revision ID: d7e3f9c1a5b8
Revises: e5f8d2a9c3b4
Create Date: 2026-06-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d7e3f9c1a5b8"
down_revision: str | None = "e5f8d2a9c3b4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "profiles",
        "own_vibe_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Анкеты без вайба не дадут вернуть NOT NULL — подчищаем их явно.
    # Это валидно только для отката на стенде; данных мы при этом не теряем,
    # кроме анкет, ожидающих модератора (они и так не участвуют в матчинге).
    op.execute("DELETE FROM profiles WHERE own_vibe_id IS NULL")
    op.alter_column(
        "profiles",
        "own_vibe_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
