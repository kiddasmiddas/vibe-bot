"""profiles_desired_vibe_nullable

Revision ID: 9c6b5e0d1a8f
Revises: 4f8a1d2e3c7b
Create Date: 2026-05-19 12:01:00.000000

Делает profiles.desired_vibe_id nullable. NULL означает «ищу любой вайб» —
пользователь не ограничивает поиск конкретным вайбом партнёра.
FK и ondelete=RESTRICT остаются без изменений.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "9c6b5e0d1a8f"
down_revision: str | None = "4f8a1d2e3c7b"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "profiles",
        "desired_vibe_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # NULL desired_vibe_id («ищу любой вайб») в старой схеме невозможен —
    # ALTER ... SET NOT NULL упал бы на таких строках. Перед откатом
    # заполняем NULL значением own_vibe_id (разумный дефолт «ищу как у себя»).
    # Откат лоссовый: признак «любой вайб» теряется — это осознанный компромисс.
    op.execute(
        "UPDATE profiles SET desired_vibe_id = own_vibe_id WHERE desired_vibe_id IS NULL"
    )
    op.alter_column(
        "profiles",
        "desired_vibe_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
