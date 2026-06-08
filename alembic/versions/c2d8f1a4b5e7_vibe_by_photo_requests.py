"""vibe_by_photo_requests

Revision ID: c2d8f1a4b5e7
Revises: a3f2c8d4e9b6
Create Date: 2026-06-08 18:00:00.000000

Premium-фича: модератор подбирает вайб пользователю по присланным 1-3 фото.

Создаёт таблицу `vibe_by_photo_requests` со связями на users, profiles, vibes.
photo_file_ids хранится строкой (file_id через ';'), max 3 шт. — ARRAY-тип
не используется, чтобы миграции не зависели от диалекта.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c2d8f1a4b5e7"
down_revision: str | None = "a3f2c8d4e9b6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "vibe_by_photo_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column(
            "photo_file_ids",
            sa.String(length=1024),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "assigned_vibe_id",
            sa.Integer(),
            sa.ForeignKey("vibes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_by_admin_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'rejected')",
            name="vbp_status_allowed",
        ),
        sa.CheckConstraint(
            "origin IN ('registration', 'profile_edit')",
            name="vbp_origin_allowed",
        ),
    )
    op.create_index(
        "ix_vbp_requests_status_created",
        "vibe_by_photo_requests",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_vbp_requests_user_id",
        "vibe_by_photo_requests",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_vbp_requests_user_id", table_name="vibe_by_photo_requests")
    op.drop_index("ix_vbp_requests_status_created", table_name="vibe_by_photo_requests")
    op.drop_table("vibe_by_photo_requests")
