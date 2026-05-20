"""seed_vibes_fandoms_interests_creator_categories_max_age

Revision ID: 3e285de43920
Revises: 579379f3fe92
Create Date: 2026-05-13 16:18:34.067650

Базовый seed справочников для регистрации (этап 3):
- vibes: 9 вайбов из коллажа исходного ТЗ (Гот, Эмо, ..., Y2K). image_file_id
  пока placeholder; админ загрузит реальные картинки через админ-режим (этап 10).
- fandoms: 15 популярных направлений anime/manga/art.
- interests: 15 интересов creator-аудитории.
- creator_categories: 5 базовых категорий для Аллеи.
- app_settings: добавляем max_age=80 + nickname_min/max_length.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "3e285de43920"
down_revision: str | None = "579379f3fe92"
branch_labels: str | None = None
depends_on: str | None = None


# --- ad-hoc table objects, не зависят от ORM ---

vibes_table = sa.table(
    "vibes",
    sa.column("code", sa.String),
    sa.column("title", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
    sa.column("number", sa.Integer),
    sa.column("image_file_id", sa.String),
)

fandoms_table = sa.table(
    "fandoms",
    sa.column("code", sa.String),
    sa.column("title", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)

interests_table = sa.table(
    "interests",
    sa.column("code", sa.String),
    sa.column("title", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)

creator_categories_table = sa.table(
    "creator_categories",
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


# --- данные ---

# Placeholder file_id формата `placeholder:vibe:<code>`. Реальные Telegram file_id
# админ положит через админ-режим в этапе 10. До тех пор бот будет показывать
# подсказку «изображение ещё не настроено» в FSM выбора вайба.
VIBES = [
    ("goth", "Гот", 1),
    ("emo", "Эмо", 2),
    ("anime_aesthetic", "Аниместетик", 3),
    ("nerd", "Нёрд", 4),
    ("tubomanka", "Тубоманка", 5),
    ("highest_aesthetic", "Высшая эстетика", 6),
    ("cyberpunk", "Киберпанк", 7),
    ("clowncore", "Кловнкор", 8),
    ("y2k", "Y2K", 9),
]

# Расширяемо через админ-режим. Стартовый набор подобран под основную нишу
# (anime/manga/art/creative).
FANDOMS = [
    ("anime", "Аниме"),
    ("manga", "Манга"),
    ("manhwa", "Манхва / манхуа"),
    ("kpop", "K-pop"),
    ("jrock_jpop", "J-rock / J-pop"),
    ("vocaloid", "Vocaloid"),
    ("fanfiction", "Фанфики"),
    ("cosplay", "Косплей"),
    ("digital_art", "Digital art"),
    ("fanart", "Fanart"),
    ("traditional_art", "Традиционное искусство"),
    ("indie_games", "Indie-игры"),
    ("jrpg", "JRPG"),
    ("visual_novels", "Визуальные новеллы"),
    ("tabletop", "Настольные игры / TTRPG"),
]

INTERESTS = [
    ("drawing", "Рисую"),
    ("writing", "Пишу"),
    ("music_making", "Делаю музыку"),
    ("singing", "Пою"),
    ("gaming", "Играю в игры"),
    ("streaming", "Стримлю"),
    ("photography", "Фотография"),
    ("cosplay_make", "Шью / делаю косплей"),
    ("animation", "Анимация / motion"),
    ("watching_anime", "Смотрю аниме"),
    ("reading", "Читаю книги"),
    ("dancing", "Танцую"),
    ("dnd_rp", "DnD / отыгрыш"),
    ("collecting", "Собираю мерч / фигурки"),
    ("languages", "Учу языки (jp/kr/en)"),
]

CREATOR_CATEGORIES = [
    ("artists", "Художники"),
    ("musicians", "Музыканты"),
    ("writers", "Авторы / писатели"),
    ("cosplayers", "Косплееры"),
    ("streamers", "Стримеры / блогеры"),
]

APP_SETTINGS = [
    ("max_age", "80", "Максимальный возраст в поле looking_for_age_max"),
    ("nickname_max_length", "32", "Максимальная длина никнейма в анкете"),
    ("nickname_min_length", "2", "Минимальная длина никнейма"),
]


def upgrade() -> None:
    op.bulk_insert(
        vibes_table,
        [
            {
                "code": code,
                "title": title,
                "is_active": True,
                "sort_order": number,
                "number": number,
                "image_file_id": f"placeholder:vibe:{code}",
            }
            for code, title, number in VIBES
        ],
    )
    op.bulk_insert(
        fandoms_table,
        [
            {"code": c, "title": t, "is_active": True, "sort_order": i}
            for i, (c, t) in enumerate(FANDOMS, start=1)
        ],
    )
    op.bulk_insert(
        interests_table,
        [
            {"code": c, "title": t, "is_active": True, "sort_order": i}
            for i, (c, t) in enumerate(INTERESTS, start=1)
        ],
    )
    op.bulk_insert(
        creator_categories_table,
        [
            {"code": c, "title": t, "is_active": True, "sort_order": i}
            for i, (c, t) in enumerate(CREATOR_CATEGORIES, start=1)
        ],
    )
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
        sa.text("DELETE FROM creator_categories WHERE code = ANY(:codes)"),
        {"codes": [c for c, _ in CREATOR_CATEGORIES]},
    )
    bind.execute(
        sa.text("DELETE FROM interests WHERE code = ANY(:codes)"),
        {"codes": [c for c, _ in INTERESTS]},
    )
    bind.execute(
        sa.text("DELETE FROM fandoms WHERE code = ANY(:codes)"),
        {"codes": [c for c, _ in FANDOMS]},
    )
    bind.execute(
        sa.text("DELETE FROM vibes WHERE code = ANY(:codes)"),
        {"codes": [c for c, _, _ in VIBES]},
    )
