"""Умный caption-бюджет карточки: списки «…и ещё N» + bio «…», структура целая.

Telegram ограничивает caption 1024 символами; рендер держит текст в
CAPTION_LIMIT − резерв под заголовок хэндлера. Старые анкеты (до лимитов
15 фандомов / 200 bio) сворачиваются без MEDIA_CAPTION_TOO_LONG.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.bot.utils.render_profile import (
    _CAPTION_RESERVE,
    CAPTION_LIMIT,
    render_profile_card,
)

_BUDGET = CAPTION_LIMIT - _CAPTION_RESERVE


def _profile(bio: str = "Чай, манга, дождь") -> SimpleNamespace:
    return SimpleNamespace(
        nickname="VibeyOne",
        age=21,
        bio=bio,
        gender_id=1,
        own_vibe_id=2,
        looking_for_age_min=18,
        looking_for_age_max=30,
        main_media_type="photo",
        main_media_file_id="AgACAg-fake",
        is_pending_review=False,
        city="Питер",
    )


def _ent(entity_id: int, title: str, number: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=entity_id, title=title, code=f"c{entity_id}", number=number)


def _render(profile, *, fandoms=(), desired_fandoms=(), interests=()):  # type: ignore[no-untyped-def]
    return render_profile_card(
        profile,
        gender=_ent(1, "Девушка"),
        own_vibe=_ent(2, "Emo", number=5),
        desired_vibes=[],
        fandoms=list(fandoms),
        desired_fandoms=list(desired_fandoms),
        interests=list(interests),
        looking_for_genders=[_ent(9, "Любой")],
    )


def test_short_card_untouched() -> None:
    rendered = _render(
        _profile(),
        fandoms=[_ent(10, "JJK"), _ent(11, "Naruto")],
        desired_fandoms=[_ent(20, "AOT")],
        interests=[_ent(30, "Чай")],
    )
    assert "…и ещё" not in rendered.text
    assert "JJK, Naruto" in rendered.text
    assert len(rendered.text) <= _BUDGET


def test_long_lists_collapse_into_more_counter() -> None:
    many = [_ent(100 + i, f"Фандом с длинным названием {i}") for i in range(30)]
    rendered = _render(
        _profile(bio="Б" * 200),
        fandoms=many,
        desired_fandoms=many,
        interests=[_ent(300 + i, f"Интерес номер {i}") for i in range(20)],
    )
    assert len(rendered.text) <= _BUDGET
    assert "…и ещё" in rendered.text
    # Хотя бы один элемент каждого списка остаётся видимым.
    assert "Фандомы: Фандом с длинным названием" in rendered.text
    # Структурные строки не тронуты.
    for anchor in ("Пол:", "Город:", "Вайб: Emo", "Возраст поиска: 18–30"):
        assert anchor in rendered.text


def test_bio_is_cut_last_with_ellipsis() -> None:
    many = [_ent(100 + i, f"Очень длинное название фандома {i}") for i in range(30)]
    rendered = _render(
        _profile(bio="Очень длинное био " * 40),  # ~720 символов, больше лимита 200
        fandoms=many,
        desired_fandoms=many,
        interests=many,
    )
    assert len(rendered.text) <= _BUDGET
    bio_line = next(line for line in rendered.text.split("\n") if line.startswith("О себе:"))
    assert bio_line.endswith("…")
    # Bio не схлопнулось в ничто.
    assert len(bio_line) > len("О себе: ") + 30


def test_html_escaping_survives_shrink() -> None:
    """Экранирование сохраняется и в свёрнутых списках, и в обрезанном bio."""
    many = [_ent(100 + i, f"Fandom <b>{i}</b>") for i in range(30)]
    rendered = _render(_profile(bio="до <script> и после " * 40), fandoms=many)
    assert "<b>" not in rendered.text
    assert "<script>" not in rendered.text
