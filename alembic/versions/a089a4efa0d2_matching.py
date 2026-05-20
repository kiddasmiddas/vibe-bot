"""matching

Revision ID: a089a4efa0d2
Revises: 141b2777c747
Create Date: 2026-05-13 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a089a4efa0d2"
down_revision: str | Sequence[str] | None = "141b2777c747"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "likes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_user_id", sa.Integer(), nullable=False),
        sa.Column("to_user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('like', 'superlike')", name=op.f("ck_likes_kind_allowed")),
        sa.CheckConstraint("from_user_id <> to_user_id", name=op.f("ck_likes_no_self_like")),
        sa.ForeignKeyConstraint(
            ["from_user_id"],
            ["users.id"],
            name=op.f("fk_likes_from_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_user_id"],
            ["users.id"],
            name=op.f("fk_likes_to_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_likes")),
        sa.UniqueConstraint("from_user_id", "to_user_id", name="uq_likes_from_to"),
    )
    op.create_index("ix_likes_to_user_id", "likes", ["to_user_id"], unique=False)

    op.create_table(
        "dislikes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_user_id", sa.Integer(), nullable=False),
        sa.Column("to_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("from_user_id <> to_user_id", name=op.f("ck_dislikes_no_self_dislike")),
        sa.ForeignKeyConstraint(
            ["from_user_id"],
            ["users.id"],
            name=op.f("fk_dislikes_from_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_user_id"],
            ["users.id"],
            name=op.f("fk_dislikes_to_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dislikes")),
        sa.UniqueConstraint("from_user_id", "to_user_id", name="uq_dislikes_from_to"),
    )
    op.create_index("ix_dislikes_from_user_id", "dislikes", ["from_user_id"], unique=False)

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_a_id", sa.Integer(), nullable=False),
        sa.Column("user_b_id", sa.Integer(), nullable=False),
        sa.Column("initial_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("user_a_id < user_b_id", name=op.f("ck_matches_user_a_lt_user_b")),
        sa.ForeignKeyConstraint(
            ["user_a_id"],
            ["users.id"],
            name=op.f("fk_matches_user_a_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_b_id"],
            ["users.id"],
            name=op.f("fk_matches_user_b_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matches")),
        sa.UniqueConstraint("user_a_id", "user_b_id", name="uq_matches_user_a_user_b"),
    )
    op.create_index("ix_matches_user_a_id", "matches", ["user_a_id"], unique=False)
    op.create_index("ix_matches_user_b_id", "matches", ["user_b_id"], unique=False)

    op.create_table(
        "viewed_profiles",
        sa.Column("viewer_user_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["viewer_user_id"],
            ["users.id"],
            name=op.f("fk_viewed_profiles_viewer_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name=op.f("fk_viewed_profiles_target_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "viewer_user_id", "target_user_id", name=op.f("pk_viewed_profiles")
        ),
    )

    op.create_table(
        "blocks",
        sa.Column("blocker_user_id", sa.Integer(), nullable=False),
        sa.Column("blocked_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["blocker_user_id"],
            ["users.id"],
            name=op.f("fk_blocks_blocker_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blocked_user_id"],
            ["users.id"],
            name=op.f("fk_blocks_blocked_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("blocker_user_id", "blocked_user_id", name=op.f("pk_blocks")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("blocks")
    op.drop_table("viewed_profiles")
    op.drop_index("ix_matches_user_b_id", table_name="matches")
    op.drop_index("ix_matches_user_a_id", table_name="matches")
    op.drop_table("matches")
    op.drop_index("ix_dislikes_from_user_id", table_name="dislikes")
    op.drop_table("dislikes")
    op.drop_index("ix_likes_to_user_id", table_name="likes")
    op.drop_table("likes")
