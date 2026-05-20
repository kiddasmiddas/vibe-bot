"""premium_payments_creators

Revision ID: 614d0b5ecd93
Revises: 141b2777c747
Create Date: 2026-05-13 16:41:28.037439

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "614d0b5ecd93"
down_revision: str | Sequence[str] | None = "141b2777c747"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # payments — финансовая запись, RESTRICT на users чтобы не каскадить вслед за удалением.
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount_kop", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_payment_charge_id", sa.String(length=128), nullable=True),
        sa.Column("telegram_payment_charge_id", sa.String(length=128), nullable=True),
        sa.Column("invoice_payload", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
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
            "status IN ('pending', 'succeeded', 'failed')", name=op.f("ck_payments_status_allowed")
        ),
        sa.CheckConstraint("amount_kop > 0", name=op.f("ck_payments_amount_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_payments_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("invoice_payload", name=op.f("uq_payments_invoice_payload")),
    )
    op.create_index("ix_payments_user_id_status", "payments", ["user_id", "status"], unique=False)

    # premium_subscriptions — FK на payments (SET NULL), отдельная связь с админом-грантователем.
    op.create_table(
        "premium_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("granted_by", sa.String(length=16), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "granted_by IN ('purchase', 'manual')",
            name=op.f("ck_premium_subscriptions_granted_by_allowed"),
        ),
        sa.CheckConstraint(
            "ends_at > started_at", name=op.f("ck_premium_subscriptions_ends_after_start")
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name=op.f("fk_premium_subscriptions_granted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_premium_subscriptions_payment_id_payments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_premium_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_premium_subscriptions")),
    )
    op.create_index(
        "ix_premium_subscriptions_user_id_ends_at",
        "premium_subscriptions",
        ["user_id", "ends_at"],
        unique=False,
    )

    # creator_posts — посты «Аллеи», ссылка на категорию RESTRICT, на пользователей SET NULL.
    op.create_table(
        "creator_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("author_display_name", sa.String(length=128), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("telegram_link", sa.String(length=256), nullable=False),
        sa.Column("is_premium_post", sa.Boolean(), nullable=False),
        sa.Column("music_file_id", sa.String(length=256), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_creator_posts_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["creator_categories.id"],
            name=op.f("fk_creator_posts_category_id_creator_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"],
            ["users.id"],
            name=op.f("fk_creator_posts_created_by_admin_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creator_posts")),
    )
    op.create_index("ix_creator_posts_category_id", "creator_posts", ["category_id"], unique=False)
    op.create_index(
        "ix_creator_posts_is_published_expires_at",
        "creator_posts",
        ["is_published", "expires_at"],
        unique=False,
    )

    # creator_post_photos — до 3 фото на пост, position 0..2, UNIQUE на пару.
    op.create_table(
        "creator_post_photos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.String(length=256), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position >= 0 AND position <= 2", name=op.f("ck_creator_post_photos_position_range")
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["creator_posts.id"],
            name=op.f("fk_creator_post_photos_post_id_creator_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creator_post_photos")),
        sa.UniqueConstraint("post_id", "position", name="post_id_position"),
    )

    # creator_submissions — заглушка под будущий流ow приёма заявок (см. модель).
    op.create_table(
        "creator_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_creator_submissions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creator_submissions")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("creator_submissions")
    op.drop_table("creator_post_photos")
    op.drop_index("ix_creator_posts_is_published_expires_at", table_name="creator_posts")
    op.drop_index("ix_creator_posts_category_id", table_name="creator_posts")
    op.drop_table("creator_posts")
    op.drop_index("ix_premium_subscriptions_user_id_ends_at", table_name="premium_subscriptions")
    op.drop_table("premium_subscriptions")
    op.drop_index("ix_payments_user_id_status", table_name="payments")
    op.drop_table("payments")
