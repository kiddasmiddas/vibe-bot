"""Юнит-тесты `app/bot/utils/render_profile.py`.

Утилита рендера принимает все справочные сущности явно — тестируем без БД,
через лёгкие SimpleNamespace-двойники.

После рефакторинга вайбов:
- параметр `desired_vibe: Vibe | None` заменён на `desired_vibes: list[Vibe]`.
- own_vibe отображается только названием "Title" (клиент убрал номер, 2026-07).
- desired_vibes выводит "A, B" (сортировка по number) или "любой" если пусто.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.bot.utils.render_profile import render_profile_card


def _profile(
    *,
    nickname: str = "VibeyOne",
    age: int = 21,
    bio: str = "Чай, манга, дождь",
    main_media_type: str = "photo",
    main_media_file_id: str = "AgACAg-fake",
    looking_for_age_min: int = 18,
    looking_for_age_max: int = 30,
    is_pending_review: bool = False,
    city: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        nickname=nickname,
        age=age,
        bio=bio,
        gender_id=1,
        own_vibe_id=2,
        looking_for_age_min=looking_for_age_min,
        looking_for_age_max=looking_for_age_max,
        main_media_type=main_media_type,
        main_media_file_id=main_media_file_id,
        is_pending_review=is_pending_review,
        city=city,
    )


def _dict_entity(entity_id: int, title: str, number: int | None = None) -> SimpleNamespace:
    ns = SimpleNamespace(id=entity_id, title=title, code=f"code{entity_id}")
    if number is not None:
        ns.number = number
    return ns


def test_render_profile_card_text_contains_all_fields() -> None:
    profile = _profile()
    gender = _dict_entity(1, "Девушка")
    own_vibe = _dict_entity(2, "Аниместетик", number=5)
    desired_vibe_a = _dict_entity(3, "Тубоманка", number=10)
    desired_vibe_b = _dict_entity(4, "Y2K", number=12)
    fandoms = [_dict_entity(10, "JJK"), _dict_entity(11, "Naruto")]
    desired_fandoms = [_dict_entity(20, "AOT")]
    interests = [_dict_entity(30, "Манга"), _dict_entity(31, "Иллюстрация")]
    looking_for_genders = [_dict_entity(4, "Парень")]

    rendered = render_profile_card(
        profile,  # type: ignore[arg-type]
        gender=gender,  # type: ignore[arg-type]
        own_vibe=own_vibe,  # type: ignore[arg-type]
        desired_vibes=[desired_vibe_a, desired_vibe_b],  # type: ignore[arg-type]
        fandoms=fandoms,  # type: ignore[arg-type]
        desired_fandoms=desired_fandoms,  # type: ignore[arg-type]
        interests=interests,  # type: ignore[arg-type]
        looking_for_genders=looking_for_genders,  # type: ignore[arg-type]
    )

    text = rendered.text
    assert "VibeyOne" in text
    assert "21" in text
    assert "Чай, манга, дождь" in text
    assert "Девушка" in text
    # own_vibe отображается только названием, без номера
    assert "Аниместетик" in text
    # desired_vibes отображаются как "Тубоманка, Y2K"
    assert "Тубоманка, Y2K" in text
    assert "№5" not in text
    assert "№10" not in text
    assert "JJK" in text
    assert "Naruto" in text
    assert "AOT" in text
    assert "Манга" in text
    assert "Иллюстрация" in text
    assert "Парень" in text
    assert "18" in text and "30" in text


def test_render_profile_card_returns_correct_media_meta() -> None:
    profile = _profile(main_media_type="video", main_media_file_id="vid:42")
    gender = _dict_entity(1, "Парень")
    own_vibe = _dict_entity(2, "Минималист", number=7)

    rendered = render_profile_card(
        profile,  # type: ignore[arg-type]
        gender=gender,  # type: ignore[arg-type]
        own_vibe=own_vibe,  # type: ignore[arg-type]
        desired_vibes=[],
        fandoms=[],
        desired_fandoms=[],
        interests=[],
        looking_for_genders=[],
    )

    assert rendered.media_type == "video"
    assert rendered.media_file_id == "vid:42"


def test_render_profile_card_handles_empty_collections() -> None:
    profile = _profile()
    gender = _dict_entity(1, "Прочее")
    own_vibe = _dict_entity(2, "Тишина", number=3)

    rendered = render_profile_card(
        profile,  # type: ignore[arg-type]
        gender=gender,  # type: ignore[arg-type]
        own_vibe=own_vibe,  # type: ignore[arg-type]
        desired_vibes=[],
        fandoms=[],
        desired_fandoms=[],
        interests=[],
        looking_for_genders=[],
    )

    # Пустые коллекции отрендерены как «—», не ломая текст.
    assert "—" in rendered.text
    # desired_vibes пустой → выводится "любой"
    assert "любой" in rendered.text


def test_render_profile_card_escapes_vibe_title() -> None:
    """Название вайба из БД экранируется (глобальный parse_mode=HTML)."""
    profile = _profile()
    gender = _dict_entity(1, "Парень")
    own_vibe = _dict_entity(2, "<b>Злой & хитрый</b>", number=5)

    rendered = render_profile_card(
        profile,  # type: ignore[arg-type]
        gender=gender,  # type: ignore[arg-type]
        own_vibe=own_vibe,  # type: ignore[arg-type]
        desired_vibes=[],
        fandoms=[],
        desired_fandoms=[],
        interests=[],
        looking_for_genders=[],
    )

    assert "&lt;b&gt;Злой &amp; хитрый&lt;/b&gt;" in rendered.text
    assert "<b>Злой" not in rendered.text


def test_render_profile_card_desired_vibes_sorted_by_number() -> None:
    """desired_vibes выводятся по возрастанию number."""
    profile = _profile()
    gender = _dict_entity(1, "Парень")
    own_vibe = _dict_entity(2, "Test", number=1)
    v10 = _dict_entity(10, "Alpha", number=10)
    v3 = _dict_entity(3, "Beta", number=3)
    v7 = _dict_entity(7, "Gamma", number=7)

    rendered = render_profile_card(
        profile,  # type: ignore[arg-type]
        gender=gender,  # type: ignore[arg-type]
        own_vibe=own_vibe,  # type: ignore[arg-type]
        desired_vibes=[v10, v3, v7],  # type: ignore[arg-type]
        fandoms=[],
        desired_fandoms=[],
        interests=[],
        looking_for_genders=[],
    )

    text = rendered.text
    # Порядок по number: Beta(3) раньше Gamma(7), Gamma раньше Alpha(10).
    assert text.index("Beta") < text.index("Gamma") < text.index("Alpha")
