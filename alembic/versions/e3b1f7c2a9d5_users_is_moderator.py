"""users_is_moderator

Revision ID: e3b1f7c2a9d5
Revises: d8f3a2c1e0b4
Create Date: 2026-05-18 00:55:00.000000

Роль модератора: колонка users.is_moderator. Модератор имеет доступ ко всей
админ-панели, кроме назначения/снятия модераторов (это только администратор).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e3b1f7c2a9d5"
down_revision: str | None = "d8f3a2c1e0b4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_moderator",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_moderator")
