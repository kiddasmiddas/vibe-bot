"""Юнит-тесты для шага city в регистрации и редактировании анкеты.

Проверяем:
- keyboard-builder city_suggestions_kb — чистая логика без БД.
- render_profile_card с city=None и desired_vibes=[] — рендерится без исключений.
- GeoService-логика, применяемая в on_city_text: единственное совпадение vs
  несколько vs ноль.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.bot.keyboards.registration import (
    CityCb,
    RegBackCb,
    city_suggestions_kb,
)
from app.bot.utils.render_profile import render_profile_card
from app.services.geo_service import CityEntry, GeoService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    city: str,
    region: str,
    *,
    population: int = 100_000,
) -> CityEntry:
    return CityEntry(
        city=city,
        region=region,
        federal_district="Тест",
        lat=None,
        lon=None,
        population=population,
    )


def _profile(
    *,
    city: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        nickname="Test",
        age=22,
        bio="Тест",
        gender_id=1,
        own_vibe_id=2,
        looking_for_age_min=18,
        looking_for_age_max=30,
        main_media_type="photo",
        main_media_file_id="AgAC-fake",
        is_pending_review=False,
        city=city,
    )


def _dict_entity(entity_id: int, title: str) -> SimpleNamespace:
    return SimpleNamespace(id=entity_id, title=title)


# ---------------------------------------------------------------------------
# city_suggestions_kb
# ---------------------------------------------------------------------------


class TestCitySuggestionsKb:
    def test_buttons_per_candidate(self) -> None:
        entries = [
            _make_entry("Казань", "Татарстан"),
            _make_entry("Москва", "Москва"),
        ]
        kb = city_suggestions_kb(entries, back_text="◀️ Назад")
        # 2 города + back = 3 кнопки в inline («Не указывать город» убрана)
        inline_buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(inline_buttons) == 3

    def test_city_button_callback_data(self) -> None:
        entries = [_make_entry("Казань", "Татарстан")]
        kb = city_suggestions_kb(entries, back_text="◀️ Назад")
        first_btn = kb.inline_keyboard[0][0]
        cb = CityCb.unpack(first_btn.callback_data)
        assert cb.city == "Казань"

    def test_no_skip_button(self) -> None:
        """Кнопки «Не указывать город» (CityCb city=\"\") больше нет."""
        entries = [_make_entry("Казань", "Татарстан")]
        kb = city_suggestions_kb(entries, back_text="◀️ Назад", keep_text="Оставить")
        flat = [btn for row in kb.inline_keyboard for btn in row]
        empty_city = [
            b
            for b in flat
            if b.callback_data.startswith("city_pick") and CityCb.unpack(b.callback_data).city == ""
        ]
        assert empty_city == []

    def test_back_button_callback_data(self) -> None:
        entries = [_make_entry("Казань", "Татарстан")]
        kb = city_suggestions_kb(entries, back_text="◀️ Назад")
        flat = [btn for row in kb.inline_keyboard for btn in row]
        back_btn = flat[-1]
        cb = RegBackCb.unpack(back_btn.callback_data)
        assert cb.step == "city_back"

    def test_keep_button_is_last(self) -> None:
        """С keep_text порядок: города → Назад → «Оставить» последней."""
        from app.bot.keyboards.registration import CityKeepCb

        entries = [_make_entry("Тайшет", "Иркутская область")]
        kb = city_suggestions_kb(entries, back_text="Назад", keep_text="✅ Оставить «Ташкент»")
        flat = [btn for row in kb.inline_keyboard for btn in row]
        assert flat[-1].callback_data == CityKeepCb().pack()
        assert flat[-1].text == "✅ Оставить «Ташкент»"
        assert RegBackCb.unpack(flat[-2].callback_data).step == "city_back"

    def test_label_includes_region(self) -> None:
        entries = [_make_entry("Ростов", "Ярославская область")]
        kb = city_suggestions_kb(entries, back_text="◀️ Назад")
        flat = [btn for row in kb.inline_keyboard for btn in row]
        assert "Ярославская область" in flat[0].text

    def test_max_buttons_capped(self) -> None:
        """Количество кнопок городов не превышает _CITY_MAX_BUTTONS=6."""
        entries = [_make_entry(f"Город{i}", "Регион") for i in range(10)]
        kb = city_suggestions_kb(entries, back_text="Назад")
        flat = [btn for row in kb.inline_keyboard for btn in row]
        # 6 городов + back = 7
        assert len(flat) == 7

    def test_empty_candidates_has_only_back(self) -> None:
        kb = city_suggestions_kb([], back_text="Назад")
        flat = [btn for row in kb.inline_keyboard for btn in row]
        assert len(flat) == 1


# ---------------------------------------------------------------------------
# render_profile_card с NULL-полями
# ---------------------------------------------------------------------------


class TestRenderProfileNullCity:
    def test_city_none_renders_dash(self) -> None:
        profile = _profile(city=None)
        gender = _dict_entity(1, "Девушка")
        own_vibe = _dict_entity(2, "Аниместетик")
        own_vibe.number = 2

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
        # Город отсутствует → поле выводится как «—»
        assert "—" in rendered.text

    def test_city_set_renders_value(self) -> None:
        profile = _profile(city="Казань")
        gender = _dict_entity(1, "Девушка")
        own_vibe = _dict_entity(2, "Аниместетик")
        own_vibe.number = 2

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
        assert "Казань" in rendered.text


class TestRenderProfileEmptyDesiredVibes:
    def test_empty_desired_vibes_renders_lyuboi(self) -> None:
        """desired_vibes=[] → карточка выводит «любой» без краша."""
        profile = _profile(city=None)
        gender = _dict_entity(1, "Парень")
        own_vibe = _dict_entity(2, "Минималист")
        own_vibe.number = 2

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
        assert "любой" in rendered.text

    def test_desired_vibes_with_items_renders_numbers(self) -> None:
        """desired_vibes=[...] → карточка выводит номера вайбов."""
        profile = _profile(city=None)
        gender = _dict_entity(1, "Парень")
        own_vibe = _dict_entity(2, "Минималист")
        own_vibe.number = 2
        desired_vibe = _dict_entity(3, "Криэйтор")
        desired_vibe.number = 3

        rendered = render_profile_card(
            profile,  # type: ignore[arg-type]
            gender=gender,  # type: ignore[arg-type]
            own_vibe=own_vibe,  # type: ignore[arg-type]
            desired_vibes=[desired_vibe],  # type: ignore[arg-type]
            fandoms=[],
            desired_fandoms=[],
            interests=[],
            looking_for_genders=[],
        )
        # Теперь вайб отображается как "№3", не по title
        assert "№3" in rendered.text


# ---------------------------------------------------------------------------
# GeoService matching logic used by on_city_text
# ---------------------------------------------------------------------------


@pytest.fixture
def geo() -> GeoService:
    entries = [
        _make_entry("Казань", "Татарстан", population=1_200_000),
        _make_entry("Ростов", "Ярославская область", population=30_000),
        _make_entry("Ростов-на-Дону", "Ростовская область", population=1_100_000),
        _make_entry("Москва", "Москва", population=12_000_000),
    ]
    return GeoService(entries)


class TestCityMatchLogic:
    """Воспроизводим логику выбора между single / multi / no match из on_city_text."""

    def test_single_match_returns_one(self, geo: GeoService) -> None:
        results = geo.match("Казань")
        assert len(results) == 1
        assert results[0].city == "Казань"

    def test_multiple_match_for_rostov(self, geo: GeoService) -> None:
        results = geo.match("Ростов")
        assert len(results) >= 2
        cities = {r.city for r in results}
        assert "Ростов" in cities
        assert "Ростов-на-Дону" in cities

    def test_no_match_returns_empty(self, geo: GeoService) -> None:
        results = geo.match("Абракадабраград")
        assert results == []

    def test_exact_match_in_multi_set(self, geo: GeoService) -> None:
        """Точное совпадение «Ростов» в наборе из нескольких — определяем по normalize."""
        results = geo.match("Ростов")
        # Нормализуем запрос и ищем точное совпадение в результатах.
        norm_query = geo.normalize("Ростов")
        exact = [e for e in results if geo.normalize(e.city) == norm_query]
        assert len(exact) == 1
        assert exact[0].city == "Ростов"

    def test_alias_spb(self, geo: GeoService) -> None:
        """Алиас «мск» резолвится в Москву."""
        results = geo.match("мск")
        assert len(results) == 1
        assert results[0].city == "Москва"


class TestCityFuzzyDetection:
    """Fuzzy-совпадения помечаются и не должны приниматься молча.

    Кейс из жалобы юзера: «Ташкент» (нет в словаре РФ) fuzzy-матчился в
    «Тайшет» и сохранялся без подтверждения.
    """

    @pytest.fixture
    def geo_with_taishet(self) -> GeoService:
        entries = [
            _make_entry("Тайшет", "Иркутская область", population=33_000),
            _make_entry("Казань", "Татарстан", population=1_200_000),
        ]
        return GeoService(entries)

    def test_tashkent_is_fuzzy_not_silent(self, geo_with_taishet: GeoService) -> None:
        result = geo_with_taishet.match_detailed("Ташкент")
        assert result.fuzzy is True
        assert [e.city for e in result.entries] == ["Тайшет"]

    def test_exact_match_is_not_fuzzy(self, geo_with_taishet: GeoService) -> None:
        result = geo_with_taishet.match_detailed("Тайшет")
        assert result.fuzzy is False
        assert [e.city for e in result.entries] == ["Тайшет"]

    def test_prefix_match_is_not_fuzzy(self, geo_with_taishet: GeoService) -> None:
        result = geo_with_taishet.match_detailed("Каза")
        assert result.fuzzy is False
        assert [e.city for e in result.entries] == ["Казань"]

    def test_no_match_is_not_fuzzy(self, geo_with_taishet: GeoService) -> None:
        result = geo_with_taishet.match_detailed("Абракадабраград")
        assert result.fuzzy is False
        assert result.entries == []

    def test_match_wrapper_returns_entries(self, geo_with_taishet: GeoService) -> None:
        assert [e.city for e in geo_with_taishet.match("Ташкент")] == ["Тайшет"]


class TestCityKeepButton:
    """Кнопка «Оставить как ввёл» появляется при keep_text."""

    def test_keep_button_present_when_keep_text(self) -> None:
        from app.bot.keyboards.registration import CityKeepCb

        kb = city_suggestions_kb(
            [],
            back_text="Назад",
            keep_text="✅ Оставить «Ташкент»",
        )
        all_buttons = [b for row in kb.inline_keyboard for b in row]
        keep = [b for b in all_buttons if b.callback_data == CityKeepCb().pack()]
        assert len(keep) == 1
        assert keep[0].text == "✅ Оставить «Ташкент»"

    def test_keep_button_absent_by_default(self) -> None:
        kb = city_suggestions_kb([], back_text="Назад")
        all_buttons = [b for row in kb.inline_keyboard for b in row]
        assert all(not b.callback_data.startswith("city_keep") for b in all_buttons)
