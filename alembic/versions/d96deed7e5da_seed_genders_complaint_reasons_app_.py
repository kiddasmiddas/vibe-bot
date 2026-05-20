"""seed_genders_complaint_reasons_app_settings

Revision ID: d96deed7e5da
Revises: c2eeceec05f2
Create Date: 2026-05-13 16:24:58.876179

Заполняет справочники полов, причин жалоб и дефолтные продуктовые настройки.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d96deed7e5da"
down_revision: str | None = "c2eeceec05f2"
branch_labels: str | None = None
depends_on: str | None = None


# Ad-hoc table objects — отдельно от ORM-моделей, чтобы миграция не зависела от их
# текущего состояния.
genders_table = sa.table(
    "genders",
    sa.column("code", sa.String),
    sa.column("title", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)

complaint_reasons_table = sa.table(
    "complaint_reasons",
    sa.column("code", sa.String),
    sa.column("title", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)

app_settings_table = sa.table(
    "app_settings",
    sa.column("key", sa.String),
    sa.column("value", sa.Text),
    sa.column("description", sa.Text),
)


GENDERS = [
    {"code": "male", "title": "Мужской", "is_active": True, "sort_order": 1},
    {"code": "female", "title": "Женский", "is_active": True, "sort_order": 2},
    {"code": "other", "title": "Другое", "is_active": True, "sort_order": 3},
]

COMPLAINT_REASONS = [
    {"code": "spam", "title": "Спам / реклама", "is_active": True, "sort_order": 1},
    {"code": "insult", "title": "Оскорбления", "is_active": True, "sort_order": 2},
    {
        "code": "inappropriate",
        "title": "Неприемлемый контент",
        "is_active": True,
        "sort_order": 3,
    },
    {"code": "fake", "title": "Фейк / обман", "is_active": True, "sort_order": 4},
    {"code": "other", "title": "Другое", "is_active": True, "sort_order": 5},
]

APP_SETTINGS = [
    # Веса алгоритма мэтчинга.
    ("match_w_fandom", "3", "Вес совпадения фандомов в скоринге мэтчинга"),
    ("match_w_vibe", "4", "Вес совпадения вайбов"),
    ("match_w_desired_fandom", "2", "Вес совпадения 'желаемых фандомов'"),
    ("match_w_interest", "1", "Вес совпадения интересов"),
    ("match_w_recency", "1", "Вес свежести анкеты (бонус за недавнее обновление)"),
    # Ограничения профиля.
    ("bio_max_length", "500", "Максимальная длина поля 'О себе'"),
    ("min_age", "18", "Минимальный возраст регистрации"),
    # Контакт модератора для кнопки 'Попасть в аллею'.
    ("creator_alley_contact_url", "", "URL/контакт модератора для подачи поста в Аллею"),
    # Тарифы Аллеи креаторов (₽).
    ("tariff_creator_post_1m", "300", "Тариф: размещение поста на 1 месяц, ₽"),
    ("tariff_creator_post_3m", "699", "Тариф: размещение поста на 3 месяца, ₽"),
    ("tariff_creator_post_6m", "1200", "Тариф: размещение поста на 6 месяцев, ₽"),
    ("tariff_creator_post_12m", "2000", "Тариф: размещение поста на 12 месяцев, ₽"),
    # Premium.
    ("premium_price_rub", "199", "Цена Premium подписки, ₽"),
    ("premium_duration_days", "30", "Длительность Premium подписки, дни"),
]


def upgrade() -> None:
    op.bulk_insert(genders_table, GENDERS)
    op.bulk_insert(complaint_reasons_table, COMPLAINT_REASONS)
    op.bulk_insert(
        app_settings_table,
        [{"key": k, "value": v, "description": d} for k, v, d in APP_SETTINGS],
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM app_settings WHERE key = ANY(:keys)"),
        {"keys": [k for k, _, _ in APP_SETTINGS]},
    )
    bind.execute(
        sa.text("DELETE FROM complaint_reasons WHERE code = ANY(:codes)"),
        {"codes": [r["code"] for r in COMPLAINT_REASONS]},
    )
    bind.execute(
        sa.text("DELETE FROM genders WHERE code = ANY(:codes)"),
        {"codes": [g["code"] for g in GENDERS]},
    )
