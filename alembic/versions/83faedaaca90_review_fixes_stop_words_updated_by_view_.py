"""review_fixes_stop_words_updated_by_view_cooldown

Revision ID: 83faedaaca90
Revises: 2b3e153c704a
Create Date: 2026-05-13 15:42:16.215001

Доработки по результатам code-review этапа 1:
- stop_words.updated_by_admin_id (): кто последним редактировал.
- app_settings: добавляем view_cooldown_days=14 для алгоритма мэтчинга
  (дефолт 14, читается в `matching_service` на этапе 4).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "83faedaaca90"
down_revision: str | None = "2b3e153c704a"
branch_labels: str | None = None
depends_on: str | None = None


_app_settings_table = sa.table(
    "app_settings",
    sa.column("key", sa.String),
    sa.column("value", sa.Text),
    sa.column("description", sa.Text),
)


def upgrade() -> None:
    op.add_column(
        "stop_words", sa.Column("updated_by_admin_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_stop_words_updated_by_admin_id_users"),
        "stop_words",
        "users",
        ["updated_by_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.bulk_insert(
        _app_settings_table,
        [
            {
                "key": "view_cooldown_days",
                "value": "14",
                "description": (
                    "Сколько дней не показывать ту же анкету повторно в мэтчинге "
                    "после просмотра"
                ),
            }
        ],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM app_settings WHERE key = 'view_cooldown_days'"))
    op.drop_constraint(
        op.f("fk_stop_words_updated_by_admin_id_users"),
        "stop_words",
        type_="foreignkey",
    )
    op.drop_column("stop_words", "updated_by_admin_id")
