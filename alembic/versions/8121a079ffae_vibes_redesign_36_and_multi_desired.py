"""vibes_redesign_36_and_multi_desired

Revision ID: 8121a079ffae
Revises: 9c6b5e0d1a8f
Create Date: 2026-05-20 00:00:00.000000

Фаза 1 рефакторинга вайбов:
- vibes.image_file_id становится nullable (админ загрузит реальные картинки позже).
- Создаётся M2M таблица profile_desired_vibes.
- Данные из profiles.desired_vibe_id мигрируются в profile_desired_vibes.
- profiles.desired_vibe_id удаляется; добавляется profiles.vibes_need_review.
- Seed расширяется с 9 до 36 вайбов; все названия унифицируются до «Вайб N».
- Все завершённые анкеты помечаются vibes_need_review=TRUE.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "8121a079ffae"
down_revision: str | None = "9c6b5e0d1a8f"
branch_labels: str | None = None
depends_on: str | None = None

# ad-hoc table references (не зависят от ORM)
profile_desired_vibes_table = sa.table(
    "profile_desired_vibes",
    sa.column("profile_id", sa.Integer),
    sa.column("vibe_id", sa.Integer),
)

vibes_table = sa.table(
    "vibes",
    sa.column("code", sa.String),
    sa.column("title", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
    sa.column("number", sa.Integer),
    sa.column("image_file_id", sa.String),
)

# Вайбы 10..36 — новые строки сида.
# image_file_id=None: реальные file_id загрузит админ через админ-режим.
NEW_VIBES = [{"code": f"vibe_{n}", "title": f"Вайб {n}", "number": n} for n in range(10, 37)]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. vibes.image_file_id — убираем NOT NULL.
    op.alter_column(
        "vibes",
        "image_file_id",
        existing_type=sa.String(length=256),
        nullable=True,
    )

    # 2. Создаём M2M таблицу profile_desired_vibes.
    op.create_table(
        "profile_desired_vibes",
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("vibe_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            name=op.f("fk_profile_desired_vibes_profile_id_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vibe_id"],
            ["vibes.id"],
            name=op.f("fk_profile_desired_vibes_vibe_id_vibes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("profile_id", "vibe_id", name=op.f("pk_profile_desired_vibes")),
    )

    # 3. Мигрируем данные: desired_vibe_id → profile_desired_vibes.
    bind.execute(
        sa.text(
            "INSERT INTO profile_desired_vibes (profile_id, vibe_id)"
            " SELECT id, desired_vibe_id FROM profiles WHERE desired_vibe_id IS NOT NULL"
        )
    )

    # 4. Удаляем FK и колонку desired_vibe_id.
    op.drop_constraint("fk_profiles_desired_vibe_id_vibes", "profiles", type_="foreignkey")
    op.drop_column("profiles", "desired_vibe_id")

    # 5. Добавляем колонку vibes_need_review.
    op.add_column(
        "profiles",
        sa.Column(
            "vibes_need_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 6. Seed расширение: унифицируем названия существующих 9 вайбов → «Вайб N».
    bind.execute(sa.text("UPDATE vibes SET title = 'Вайб ' || number::text"))

    # 7. Добавляем вайбы 10..36.
    op.bulk_insert(
        vibes_table,
        [
            {
                "code": v["code"],
                "title": v["title"],
                "is_active": True,
                "sort_order": v["number"],
                "number": v["number"],
                "image_file_id": None,
            }
            for v in NEW_VIBES
        ],
    )

    # 8. Помечаем все завершённые анкеты как требующие переподтверждения вайбов.
    bind.execute(sa.text("UPDATE profiles SET vibes_need_review = TRUE WHERE is_completed = TRUE"))


def downgrade() -> None:
    bind = op.get_bind()

    # 1. Удаляем вайбы 10..36.
    bind.execute(sa.text("DELETE FROM vibes WHERE number BETWEEN 10 AND 36"))

    # TODO(фаза-downgrade): исходные названия вайбов 1..9 («Гот», «Эмо», ..., «Y2K»)
    # не восстанавливаются — downgrade лоссовый по именам. В проде downgrade не запускают.

    # 2. Удаляем колонку vibes_need_review.
    op.drop_column("profiles", "vibes_need_review")

    # 3. Возвращаем колонку desired_vibe_id + FK.
    op.add_column(
        "profiles",
        sa.Column("desired_vibe_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_profiles_desired_vibe_id_vibes",
        "profiles",
        "vibes",
        ["desired_vibe_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 4. Лоссовое восстановление: берём первый vibe_id из M2M для каждого профиля.
    bind.execute(
        sa.text(
            "UPDATE profiles"
            " SET desired_vibe_id = ("
            "   SELECT MIN(vibe_id) FROM profile_desired_vibes"
            "   WHERE profile_id = profiles.id"
            " )"
        )
    )

    # 5. Удаляем таблицу profile_desired_vibes.
    op.drop_table("profile_desired_vibes")

    # 6. Возвращаем NOT NULL на image_file_id, предварительно заполняя NULL.
    bind.execute(
        sa.text(
            "UPDATE vibes SET image_file_id = 'placeholder:vibe:' || code"
            " WHERE image_file_id IS NULL"
        )
    )
    op.alter_column(
        "vibes",
        "image_file_id",
        existing_type=sa.String(length=256),
        nullable=False,
    )
