"""Юнит-тесты для логики сборки caption жалобы и show_screen-хелпера.

Проверяет:
- truncate_caption: обрезку длинного текста с многоточием.
- _build_caption: корректную сборку caption для медиа-карточки.
- _fmt_username: форматирование @username / fallback.

Без БД, без aiogram — только чистая логика.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.bot.handlers.admin._helpers import truncate_caption
from app.bot.handlers.admin.complaints import _build_caption, _fmt_username

# ---------------------------------------------------------------------------
# truncate_caption
# ---------------------------------------------------------------------------


def test_truncate_caption_short_text_unchanged() -> None:
    short = "Привет, это тест"
    assert truncate_caption(short) == short


def test_truncate_caption_exact_limit_unchanged() -> None:
    text = "x" * 1024
    assert truncate_caption(text) == text


def test_truncate_caption_one_over_limit() -> None:
    text = "x" * 1025
    result = truncate_caption(text)
    assert len(result) == 1024
    assert result.endswith("…")


def test_truncate_caption_long_text() -> None:
    text = "A" * 2000
    result = truncate_caption(text)
    assert len(result) == 1024
    assert result.endswith("…")


def test_truncate_caption_custom_limit() -> None:
    text = "ABCDE"
    result = truncate_caption(text, limit=4)
    assert len(result) == 4
    assert result.endswith("…")


# ---------------------------------------------------------------------------
# _fmt_username
# ---------------------------------------------------------------------------


def test_fmt_username_with_value() -> None:
    assert _fmt_username("myuser") == "@myuser"


def test_fmt_username_none_returns_fallback() -> None:
    assert _fmt_username(None, fallback="id=123") == "id=123"


def test_fmt_username_none_empty_fallback() -> None:
    assert _fmt_username(None) == ""


# ---------------------------------------------------------------------------
# _build_caption — с анкетой
# ---------------------------------------------------------------------------


def _make_detail(
    *,
    violator_username: str | None = "violator_tg",
    reporter_username: str | None = "reporter_tg",
    violator_id: int = 10,
    reporter_tg_id: int = 20,
    complaint_id: int = 42,
    comment: str | None = "спам",
    reason_id: int = 1,
    has_profile: bool = True,
) -> SimpleNamespace:
    """Минимальный двойник ComplaintWithDetails для тестов."""
    complaint = SimpleNamespace(
        id=complaint_id,
        from_user_id=5,
        target_user_id=violator_id,
        reason_id=reason_id,
        comment=comment,
        status="new",
    )
    violator = SimpleNamespace(id=violator_id, username=violator_username, telegram_id=99)
    reporter = SimpleNamespace(id=5, username=reporter_username, telegram_id=reporter_tg_id)
    profile = SimpleNamespace(user_id=violator_id) if has_profile else None
    return SimpleNamespace(
        complaint=complaint,
        violator=violator,
        violator_profile=profile,
        reporter=reporter,
    )


def test_build_caption_with_profile_contains_all_parts() -> None:
    detail = _make_detail()
    caption = _build_caption(
        detail,  # type: ignore[arg-type]
        profile_text="Никнейм, 21\nБиография",
        reason_title="Спам",
        page=1,
        total=5,
    )
    assert "@violator_tg" in caption
    assert "@reporter_tg" in caption
    assert "Спам" in caption
    assert "спам" in caption  # comment
    assert "1/5" in caption
    assert "#42" in caption


def test_build_caption_with_profile_username_appended_to_first_line() -> None:
    detail = _make_detail(violator_username="vibe_user")
    caption = _build_caption(
        detail,  # type: ignore[arg-type]
        profile_text="VibeyOne, 25\nБио текст",
        reason_title="NSFW",
        page=2,
        total=3,
    )
    # @username должен быть рядом с первой строкой.
    lines = caption.splitlines()
    first_line = lines[0]
    assert "VibeyOne, 25" in first_line
    assert "@vibe_user" in first_line


def test_build_caption_no_username_no_at_sign() -> None:
    detail = _make_detail(violator_username=None)
    caption = _build_caption(
        detail,  # type: ignore[arg-type]
        profile_text="VibeyOne, 25\nБио текст",
        reason_title="Оскорбления",
        page=1,
        total=1,
    )
    # Не должно быть @ для нарушителя — только для репортера.
    lines = caption.splitlines()
    assert "@" not in lines[0]
    assert "@reporter_tg" in caption


def test_build_caption_no_profile_uses_fallback_template() -> None:
    detail = _make_detail(violator_username=None, has_profile=False)
    caption = _build_caption(
        detail,  # type: ignore[arg-type]
        profile_text=None,
        reason_title="Мошенничество",
        page=3,
        total=7,
    )
    assert "user_id=" in caption or "Нарушитель" in caption
    assert "Мошенничество" in caption
    assert "3/7" in caption


def test_build_caption_no_comment_shows_dash() -> None:
    detail = _make_detail(comment=None)
    caption = _build_caption(
        detail,  # type: ignore[arg-type]
        profile_text="Name, 20",
        reason_title="Спам",
        page=1,
        total=1,
    )
    assert "—" in caption


def test_build_caption_total_length_respects_limit_after_truncate() -> None:
    """Убедимся, что truncate_caption применима к результату _build_caption."""
    detail = _make_detail()
    long_profile = "А" * 900
    caption = _build_caption(
        detail,  # type: ignore[arg-type]
        profile_text=long_profile,
        reason_title="X" * 50,
        page=1,
        total=99,
    )
    truncated = truncate_caption(caption)
    assert len(truncated) <= 1024
