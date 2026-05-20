"""add_no_self_block_check

Revision ID: 36cb6e03a0d0
Revises: 3e285de43920
Create Date: 2026-05-14 17:51:59.890502

CHECK по согласованности с Like.no_self_like / Dislike.no_self_dislike.
Autogen такие ограничения не подхватывает — пишем руками.
"""

from __future__ import annotations

from alembic import op

revision: str = "36cb6e03a0d0"
down_revision: str | None = "3e285de43920"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_blocks_no_self_block",
        "blocks",
        "blocker_user_id <> blocked_user_id",
    )


def downgrade() -> None:
    op.drop_constraint("ck_blocks_no_self_block", "blocks", type_="check")
