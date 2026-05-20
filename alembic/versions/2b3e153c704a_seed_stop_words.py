"""seed_stop_words

Revision ID: 2b3e153c704a
Revises: 9f7eb4bc0d54
Create Date: 2026-05-13 15:34:11.924908

Базовый набор стоп-слов:
- link: regex'ы на http/https URL, t.me/ инвайты и @username-упоминания.
- hate_speech / adult_keyword: PLACEHOLDER-ы. Реальные термины должны быть
  согласованы с заказчиком и добавлены через админский режим бота. До согласования placeholder-ы дают возможность тестировать
  пайплайн модерации, не выкладывая чувствительные термины в git.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "2b3e153c704a"
down_revision: str | None = "9f7eb4bc0d54"
branch_labels: str | None = None
depends_on: str | None = None


stop_words_table = sa.table(
    "stop_words",
    sa.column("pattern", sa.String),
    sa.column("kind", sa.String),
    sa.column("category", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("notes", sa.Text),
)


LINK_PATTERNS: list[dict[str, object]] = [
    {
        "pattern": r"https?://\S+",
        "kind": "regex",
        "category": "link",
        "is_active": True,
        "notes": "base seed v1: любая http/https ссылка",
    },
    {
        "pattern": r"t\.me/\S+",
        "kind": "regex",
        "category": "link",
        "is_active": True,
        "notes": "base seed v1: telegram invite",
    },
    {
        "pattern": r"(?<![\w@])@[A-Za-z0-9_]{4,}",
        "kind": "regex",
        "category": "link",
        "is_active": True,
        "notes": "base seed v1: @username mention (negative lookbehind чтобы не ловить e-mail)",
    },
]


# Placeholder-наборы: использовать как «hate_speech» / «adult_keyword» можно сразу,
# но реальные термины должны заменить эти placeholder-ы через админку.
HATE_SPEECH_PLACEHOLDERS: list[dict[str, object]] = [
    {
        "pattern": f"placeholder_hate_{i}",
        "kind": "word",
        "category": "hate_speech",
        "is_active": True,
        "notes": "BASE SEED V1 — placeholder, заменить реальным термином после согласования",
    }
    for i in range(1, 6)
]

ADULT_KEYWORD_PLACEHOLDERS: list[dict[str, object]] = [
    {
        "pattern": f"placeholder_adult_{i}",
        "kind": "word",
        "category": "adult_keyword",
        "is_active": True,
        "notes": "BASE SEED V1 — placeholder, расширить через админку бота",
    }
    for i in range(1, 6)
]


ALL_SEED_ROWS = LINK_PATTERNS + HATE_SPEECH_PLACEHOLDERS + ADULT_KEYWORD_PLACEHOLDERS


def upgrade() -> None:
    op.bulk_insert(stop_words_table, ALL_SEED_ROWS)


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM stop_words WHERE pattern = ANY(:patterns)").bindparams(
            patterns=[r["pattern"] for r in ALL_SEED_ROWS]
        )
    )
