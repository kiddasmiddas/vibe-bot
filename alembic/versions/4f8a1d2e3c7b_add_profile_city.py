"""add_profile_city

Revision ID: 4f8a1d2e3c7b
Revises: e3b1f7c2a9d5
Create Date: 2026-05-19 12:00:00.000000

Добавляет колонку profiles.city (String(80), nullable) и индекс по ней.
Nullable — чтобы не сломать существующие анкеты на проде (NOT NULL без
server_default уронил бы миграцию). Обязательность при регистрации
обеспечивает хендлер, не схема.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "4f8a1d2e3c7b"
down_revision: str | None = "e3b1f7c2a9d5"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("city", sa.String(length=80), nullable=True))
    op.create_index("ix_profiles_city", "profiles", ["city"])


def downgrade() -> None:
    op.drop_index("ix_profiles_city", table_name="profiles")
    op.drop_column("profiles", "city")
