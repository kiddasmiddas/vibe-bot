"""Юнит-тесты для app/services/geo_service.py."""

from __future__ import annotations

import pytest

from app.services.geo_service import ALIASES, REGION_GROUPS, CityEntry, GeoService, get_geo_service

# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------


def _make_entry(
    city: str,
    region: str,
    *,
    federal_district: str = "Тестовый",
    lat: float | None = None,
    lon: float | None = None,
    population: int = 10_000,
) -> CityEntry:
    return CityEntry(
        city=city,
        region=region,
        federal_district=federal_district,
        lat=lat,
        lon=lon,
        population=population,
    )


@pytest.fixture
def tiny_service() -> GeoService:
    """Минимальный датасет для изолированных тестов без реального JSON."""
    entries = [
        _make_entry("Москва", "Москва", population=12_000_000),
        _make_entry("Балашиха", "Московская область", population=500_000),
        _make_entry("Подольск", "Московская область", population=300_000),
        _make_entry("Санкт-Петербург", "Санкт-Петербург", population=5_000_000),
        _make_entry("Гатчина", "Ленинградская область", population=100_000),
        _make_entry("Севастополь", "Севастополь", population=200_000),
        _make_entry("Симферополь", "Крым", population=300_000),
        _make_entry("Ростов", "Ярославская область", population=30_000),
        _make_entry("Ростов-на-Дону", "Ростовская область", population=1_100_000),
        _make_entry("Казань", "Татарстан", population=1_200_000),
        _make_entry("Екатеринбург", "Свердловская область", population=1_500_000),
        _make_entry("Новосибирск", "Новосибирская область", population=1_600_000),
        _make_entry("Нижний Новгород", "Нижегородская область", population=1_200_000),
    ]
    return GeoService(entries)


# ---------------------------------------------------------------------------
# Тесты нормализации
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_lower(self) -> None:
        assert GeoService.normalize("КАЗАНЬ") == "казань"

    def test_yo_to_ye(self) -> None:
        # «ё» → «е»
        assert GeoService.normalize("Орёл") == "орел"

    def test_trim(self) -> None:
        assert GeoService.normalize("  Москва  ") == "москва"

    def test_collapse_spaces(self) -> None:
        assert GeoService.normalize("Нижний   Новгород") == "нижний новгород"

    def test_strip_prefix_g_dot(self) -> None:
        assert GeoService.normalize("г. Москва") == "москва"

    def test_strip_prefix_gorod(self) -> None:
        assert GeoService.normalize("город Казань") == "казань"

    def test_strip_prefix_case_insensitive(self) -> None:
        assert GeoService.normalize("Г. Казань") == "казань"

    def test_empty(self) -> None:
        assert GeoService.normalize("") == ""


# ---------------------------------------------------------------------------
# Тесты алиасов
# ---------------------------------------------------------------------------


class TestAliases:
    def test_piter_resolves_to_spb(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("питер")
        assert len(results) == 1
        assert results[0].city == "Санкт-Петербург"

    def test_spb_alias(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("СПб")
        assert len(results) == 1
        assert results[0].city == "Санкт-Петербург"

    def test_msk_alias(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("мск")
        assert len(results) == 1
        assert results[0].city == "Москва"

    def test_ekb_alias(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("екб")
        assert len(results) == 1
        assert results[0].city == "Екатеринбург"

    def test_ekat_alias(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("екат")
        assert len(results) == 1
        assert results[0].city == "Екатеринбург"

    def test_nsk_alias(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("нск")
        assert len(results) == 1
        assert results[0].city == "Новосибирск"

    def test_nizhniy_alias(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("нижний")
        assert len(results) == 1
        assert results[0].city == "Нижний Новгород"

    def test_alias_keys_are_normalized(self) -> None:
        """Все ключи в ALIASES уже в нормализованной форме (lower, ё→е)."""
        for key in ALIASES:
            assert key == GeoService.normalize(key), (
                f"Alias key {key!r} не совпадает со своей нормализованной версией"
            )


# ---------------------------------------------------------------------------
# Тесты точного совпадения
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_exact_canonical(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("Казань")
        assert len(results) == 1
        assert results[0].city == "Казань"

    def test_exact_case_insensitive(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("КАЗАНЬ")
        assert len(results) == 1
        assert results[0].city == "Казань"

    def test_exact_with_g_prefix(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("г. Казань")
        assert len(results) == 1
        assert results[0].city == "Казань"

    def test_exact_with_gorod_prefix(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("город Казань")
        assert len(results) == 1
        assert results[0].city == "Казань"

    def test_exact_yo_insensitive(self, tiny_service: GeoService) -> None:
        # Орёл нет в датасете, но нормализация «ё→е» должна работать при поиске.
        svc = GeoService([_make_entry("Орёл", "Орловская область")])
        assert svc.match("Орел")[0].city == "Орёл"
        assert svc.match("Орёл")[0].city == "Орёл"


# ---------------------------------------------------------------------------
# Тесты неоднозначности
# ---------------------------------------------------------------------------


class TestAmbiguity:
    def test_rostov_ambiguous(self, tiny_service: GeoService) -> None:
        """«Ростов» без уточнения возвращает несколько городов (или substring)."""
        results = tiny_service.match("Ростов")
        # Оба Ростова должны присутствовать в результатах.
        cities = {r.city for r in results}
        assert "Ростов" in cities
        assert "Ростов-на-Дону" in cities

    def test_rostov_sorted_by_population(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("Ростов")
        # Ростов-на-Дону (1.1M) должен быть первым.
        assert results[0].city == "Ростов-на-Дону"


# ---------------------------------------------------------------------------
# Тесты fuzzy
# ---------------------------------------------------------------------------


class TestFuzzy:
    def test_typo_kazan(self, tiny_service: GeoService) -> None:
        # «Казань» с опечаткой «Кзань» — должен найти fuzzy.
        results = tiny_service.match("Кзань")
        assert len(results) >= 1
        assert results[0].city == "Казань"

    def test_typo_novosibirsk(self, tiny_service: GeoService) -> None:
        # Небольшая опечатка.
        results = tiny_service.match("Новосибирс")
        assert len(results) >= 1
        assert results[0].city == "Новосибирск"

    def test_empty_query(self, tiny_service: GeoService) -> None:
        assert tiny_service.match("") == []

    def test_whitespace_only(self, tiny_service: GeoService) -> None:
        assert tiny_service.match("   ") == []

    def test_unknown_city_returns_empty(self, tiny_service: GeoService) -> None:
        results = tiny_service.match("Абракадабраград")
        assert results == []


# ---------------------------------------------------------------------------
# Тесты get / region_of / is_known
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_found(self, tiny_service: GeoService) -> None:
        entry = tiny_service.get("Казань")
        assert entry is not None
        assert entry.city == "Казань"
        assert entry.region == "Татарстан"

    def test_get_not_found(self, tiny_service: GeoService) -> None:
        assert tiny_service.get("Несуществующий") is None

    def test_region_of_found(self, tiny_service: GeoService) -> None:
        assert tiny_service.region_of("Казань") == "Татарстан"

    def test_region_of_not_found(self, tiny_service: GeoService) -> None:
        assert tiny_service.region_of("Несуществующий") is None

    def test_is_known_true(self, tiny_service: GeoService) -> None:
        assert tiny_service.is_known("Казань") is True

    def test_is_known_false(self, tiny_service: GeoService) -> None:
        assert tiny_service.is_known("Несуществующий") is False

    def test_is_known_case_insensitive(self, tiny_service: GeoService) -> None:
        assert tiny_service.is_known("казань") is True


# ---------------------------------------------------------------------------
# Тесты neighbor_cities + REGION_GROUPS
# ---------------------------------------------------------------------------


class TestNeighborCities:
    def test_same_region_returned(self, tiny_service: GeoService) -> None:
        neighbors = tiny_service.neighbor_cities("Балашиха")
        assert "Подольск" in neighbors

    def test_exclude_self_default(self, tiny_service: GeoService) -> None:
        neighbors = tiny_service.neighbor_cities("Балашиха")
        assert "Балашиха" not in neighbors

    def test_include_self(self, tiny_service: GeoService) -> None:
        neighbors = tiny_service.neighbor_cities("Балашиха", exclude_self=False)
        assert "Балашиха" in neighbors

    def test_moskva_includes_moskovskaya_oblast(self, tiny_service: GeoService) -> None:
        """Москва (регион «Москва») должна тянуть города Московской области."""
        neighbors = tiny_service.neighbor_cities("Москва")
        assert "Балашиха" in neighbors
        assert "Подольск" in neighbors

    def test_moskovskaya_oblast_includes_moskva(self, tiny_service: GeoService) -> None:
        """Балашиха (МО) должна тянуть саму Москву."""
        neighbors = tiny_service.neighbor_cities("Балашиха")
        assert "Москва" in neighbors

    def test_spb_includes_leningradskaya_oblast(self, tiny_service: GeoService) -> None:
        neighbors = tiny_service.neighbor_cities("Санкт-Петербург")
        assert "Гатчина" in neighbors

    def test_leningradskaya_oblast_includes_spb(self, tiny_service: GeoService) -> None:
        neighbors = tiny_service.neighbor_cities("Гатчина")
        assert "Санкт-Петербург" in neighbors

    def test_sevastopol_includes_crimea(self, tiny_service: GeoService) -> None:
        neighbors = tiny_service.neighbor_cities("Севастополь")
        assert "Симферополь" in neighbors

    def test_crimea_includes_sevastopol(self, tiny_service: GeoService) -> None:
        neighbors = tiny_service.neighbor_cities("Симферополь")
        assert "Севастополь" in neighbors

    def test_sorted_by_population_descending(self, tiny_service: GeoService) -> None:
        neighbors = tiny_service.neighbor_cities("Москва")
        # Балашиха (500k) должна идти раньше Подольска (300k).
        assert neighbors.index("Балашиха") < neighbors.index("Подольск")

    def test_unknown_city_returns_empty(self, tiny_service: GeoService) -> None:
        assert tiny_service.neighbor_cities("Несуществующий") == []

    def test_isolated_region_no_cross_bleed(self, tiny_service: GeoService) -> None:
        """Казань (Татарстан) не должна смешиваться с Московским регионом."""
        neighbors = tiny_service.neighbor_cities("Казань")
        assert "Москва" not in neighbors
        assert "Балашиха" not in neighbors


# ---------------------------------------------------------------------------
# Тест singleton на реальном датасете
# ---------------------------------------------------------------------------


class TestRealDataset:
    def test_singleton_loaded(self) -> None:
        svc = get_geo_service()
        # Датасет содержит 1134 города.
        assert svc.is_known("Казань")
        assert svc.is_known("Москва")
        assert svc.is_known("Санкт-Петербург")

    def test_singleton_is_same_object(self) -> None:
        assert get_geo_service() is get_geo_service()

    def test_real_piter_alias(self) -> None:
        results = get_geo_service().match("питер")
        assert results[0].city == "Санкт-Петербург"

    def test_real_moskva_neighbors_include_mo(self) -> None:
        neighbors = get_geo_service().neighbor_cities("Москва")
        assert "Балашиха" in neighbors

    def test_real_rostov_ambiguous(self) -> None:
        results = get_geo_service().match("Ростов")
        cities = {r.city for r in results}
        assert "Ростов" in cities
        assert "Ростов-на-Дону" in cities


# ---------------------------------------------------------------------------
# Тест модульных констант
# ---------------------------------------------------------------------------


class TestConstants:
    def test_region_groups_are_frozensets(self) -> None:
        for group in REGION_GROUPS:
            assert isinstance(group, frozenset)

    def test_region_groups_contain_expected_pairs(self) -> None:
        all_regions = set().union(*REGION_GROUPS)
        assert "Москва" in all_regions
        assert "Московская область" in all_regions
        assert "Санкт-Петербург" in all_regions
        assert "Ленинградская область" in all_regions
        assert "Севастополь" in all_regions
        assert "Крым" in all_regions
