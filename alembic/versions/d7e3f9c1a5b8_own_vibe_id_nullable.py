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
    # ВНИМАНИЕ: вернуть NOT NULL нельзя, пока есть анкеты с own_vibe_id IS NULL
    # (ждут вайб от модератора). НЕ удаляем их молча — это живые анкеты
    # оплативших Premium пользователей. Вместо тихого DELETE падаем с понятной
    # инструкцией: оператор должен сначала разрулить такие анкеты вручную
    # (назначить вайб или снять с бэкапом), затем повторить downgrade.
    bind = op.get_bind()
    count = bind.execute(
        sa.text("SELECT count(*) FROM profiles WHERE own_vibe_id IS NULL")
    ).scalar()
    if count:
        raise RuntimeError(
            f"Downgrade aborted: {count} profile(s) have own_vibe_id IS NULL "
            "(awaiting moderator vibe). Assign vibes or remove these rows manually "
            "(with a backup) before downgrading — refusing to delete user profiles."
        )
    op.alter_column(
        "profiles",
        "own_vibe_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
