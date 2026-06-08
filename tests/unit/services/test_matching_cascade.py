"""Юнит-тесты каскадной фильтрации по городу и хард-фильтра по вайбу.

Тестирует без БД:
* `_vibe_match_points` с None-значениями desired_vibe_id.
* `MatchingService._fetch_candidates_cascade` через AsyncMock-заглушку репозитория.
* `CandidateResult` флаги (from_neighbor_city / from_other_region).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.matching_service import (
    CandidateRelations,
    CandidateResult,
    MatchingService,
    MatchingWeights,
    _score_candidate,
    _vibe_match_points,
)

NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile(
    *,
    profile_id: int = 1,
    user_id: int = 1,
    own_vibe_id: int = 100,
    desired_vibe_id: int | None = 200,
    days_old: int = 1,
    city: str | None = None,
    gender_id: int = 1,
    looking_for_age_min: int = 18,
    looking_for_age_max: int = 60,
    age: int = 25,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=profile_id,
        user_id=user_id,
        own_vibe_id=own_vibe_id,
        desired_vibe_id=desired_vibe_id,
        created_at=NOW - timedelta(days=days_old),
        city=city,
        gender_id=gender_id,
        looking_for_age_min=looking_for_age_min,
        looking_for_age_max=looking_for_age_max,
        age=age,
    )


def _weights() -> MatchingWeights:
    return MatchingWeights(
        w_fandom=3.0,
        w_vibe=4.0,
        w_desired_fandom=2.0,
        w_interest=1.0,
        w_recency=1.0,
    )


# ---------------------------------------------------------------------------
# _vibe_match_points — NULL-безопасность
# ---------------------------------------------------------------------------


def test_vibe_match_my_desired_empty_gives_zero_b_side() -> None:
    """Мой desired_vibe пустой → сторона B несовпавшая, но сторона A может совпасть."""
    # my_own=1, my_desired={}; their_own=5, their_desired={1}
    # a = (1 in {1}) True; b = (bool({}) and ...) False → 2
    assert _vibe_match_points(1, frozenset(), 5, frozenset({1})) == 2


def test_vibe_match_their_desired_empty_gives_zero_a_side() -> None:
    """Их desired_vibe пустой → сторона A несовпавшая, но сторона B может совпасть."""
    # my_own=1, my_desired={5}; their_own=5, their_desired={}
    # a = (bool({}) and ...) False; b = (5 in {5}) True → 2
    assert _vibe_match_points(1, frozenset({5}), 5, frozenset()) == 2


def test_vibe_match_both_desired_empty_gives_zero() -> None:
    """Оба desired_vibe пусты → оба нуля, итог 0."""
    assert _vibe_match_points(1, frozenset(), 2, frozenset()) == 0


def test_vibe_match_my_desired_empty_two_way_impossible() -> None:
    """Если мой desired пустой — двустороннее совпадение невозможно (максимум 2)."""
    # my_own=1, my_desired={}; their_own=99, their_desired={1} → a=True, b=False → 2
    result = _vibe_match_points(1, frozenset(), 99, frozenset({1}))
    assert result == 2


def test_vibe_match_non_empty_two_way() -> None:
    """Стандартный кейс двустороннего совпадения при непустых desired."""
    assert _vibe_match_points(1, frozenset({2}), 2, frozenset({1})) == 4


def test_vibe_match_non_empty_zero() -> None:
    """Без совпадений → 0."""
    assert _vibe_match_points(1, frozenset({2}), 3, frozenset({4})) == 0


# ---------------------------------------------------------------------------
# _score_candidate — desired_vibe_id=None не падает
# ---------------------------------------------------------------------------


def test_score_candidate_desired_vibe_none_does_not_crash() -> None:
    """Скоринг не падает, если у меня или у кандидата desired_vibe_id IS NULL."""
    me = _profile(profile_id=1, user_id=1, own_vibe_id=1, desired_vibe_id=None, days_old=0)
    them = _profile(profile_id=2, user_id=2, own_vibe_id=1, desired_vibe_id=None, days_old=0)
    result = _score_candidate(
        my_profile=me,
        my_relations=CandidateRelations(),
        their_profile=them,
        their_relations=CandidateRelations(),
        weights=_weights(),
        now=NOW,
    )
    # Вайбы не совпали (оба None desired), fandom/interest=0, recency=1.0.
    assert result.breakdown["vibe"] == 0.0
    assert result.score == 1.0  # только recency


def test_score_candidate_my_desired_empty_their_desired_set() -> None:
    """my.desired=пусто, their.desired ⊇ {my.own} → одностороннее совпадение (a-сторона)."""
    me = _profile(profile_id=1, user_id=1, own_vibe_id=7, desired_vibe_id=None, days_old=0)
    them = _profile(profile_id=2, user_id=2, own_vibe_id=99, desired_vibe_id=7, days_old=0)
    result = _score_candidate(
        my_profile=me,
        my_relations=CandidateRelations(desired_vibe_ids=frozenset()),
        their_profile=them,
        their_relations=CandidateRelations(desired_vibe_ids=frozenset({7})),
        weights=_weights(),
        now=NOW,
    )
    # vibe_points=2, w_vibe=4 → 8, recency=1 → total=9
    assert result.breakdown["vibe"] == 8.0
    assert result.score == 9.0


# ---------------------------------------------------------------------------
# _fetch_candidates_cascade — через замоканный MatchingRepository
# ---------------------------------------------------------------------------


def _make_service(matching_repo_mock: Any) -> MatchingService:
    """Создаёт MatchingService с замоканным matching_repo.

    profile_repo, settings_repo, dictionary_repo не нужны для
    _fetch_candidates_cascade — передаём тоже моки, чтобы не падать.
    """
    profile_repo = MagicMock()
    settings_repo = MagicMock()
    dictionary_repo = MagicMock()
    return MatchingService(
        profile_repo=profile_repo,
        matching_repo=matching_repo_mock,
        settings_repo=settings_repo,
        dictionary_repo=dictionary_repo,
    )


@pytest.mark.asyncio
async def test_cascade_stage1_returns_own_city_candidates() -> None:
    """Stage 1 находит кандидатов → флаги both False."""
    my_prof = _profile(city="Казань", desired_vibe_id=5)
    cand = _profile(profile_id=2, user_id=2, city="Казань")

    repo = MagicMock()
    repo.find_candidates = AsyncMock(return_value=[cand])

    svc = _make_service(repo)
    profiles, neighbor, other = await svc._fetch_candidates_cascade(
        my_profile=my_prof,
        my_looking_for_gender_ids=[1],
        excluded_user_ids=set(),
        desired_vibe_ids=frozenset({5}),
    )
    assert profiles == [cand]
    assert neighbor is False
    assert other is False
    # find_candidates вызван 1 раз (только Stage 1).
    assert repo.find_candidates.call_count == 1
    call_kwargs = repo.find_candidates.call_args.kwargs
    assert call_kwargs["city_filter"] == ["Казань"]
    assert call_kwargs["desired_vibe_ids"] == frozenset({5})


@pytest.mark.asyncio
async def test_cascade_stage2_when_stage1_empty() -> None:
    """Stage 1 пуст, Stage 2 (соседние города) находит кандидатов → from_neighbor_city=True."""
    my_prof = _profile(city="Казань", desired_vibe_id=None)
    cand = _profile(profile_id=2, user_id=2, city="Набережные Челны")

    # Stage 1 → пусто, Stage 2 → [cand].
    repo = MagicMock()
    repo.find_candidates = AsyncMock(side_effect=[[], [cand]])

    svc = _make_service(repo)

    # GeoService.neighbor_cities должен вернуть непустой список, иначе Stage 3.
    with patch("app.services.matching_service.get_geo_service") as mock_geo_factory:
        mock_geo = MagicMock()
        mock_geo.neighbor_cities.return_value = ["Набережные Челны", "Нижнекамск"]
        mock_geo_factory.return_value = mock_geo

        profiles, neighbor, other = await svc._fetch_candidates_cascade(
            my_profile=my_prof,
            my_looking_for_gender_ids=[1],
            excluded_user_ids=set(),
            desired_vibe_ids=frozenset(),
        )

    assert profiles == [cand]
    assert neighbor is True
    assert other is False
    assert repo.find_candidates.call_count == 2
    # Второй вызов — Stage 2 с city_filter=соседи.
    stage2_kwargs = repo.find_candidates.call_args_list[1].kwargs
    assert set(stage2_kwargs["city_filter"]) == {"Набережные Челны", "Нижнекамск"}
    # desired_vibe_ids=пустой → не фильтруем по вайбу.
    assert stage2_kwargs["desired_vibe_ids"] == frozenset()


@pytest.mark.asyncio
async def test_cascade_stage3_when_stage1_and_stage2_empty() -> None:
    """Stage 1 и Stage 2 пусты → Stage 3 (global) → from_other_region=True."""
    my_prof = _profile(city="Казань", desired_vibe_id=3)
    cand = _profile(profile_id=2, user_id=2, city="Владивосток")

    # Stage 1 → [], Stage 2 → [], Stage 3 → [cand].
    repo = MagicMock()
    repo.find_candidates = AsyncMock(side_effect=[[], [], [cand]])

    svc = _make_service(repo)

    with patch("app.services.matching_service.get_geo_service") as mock_geo_factory:
        mock_geo = MagicMock()
        mock_geo.neighbor_cities.return_value = ["Набережные Челны"]
        mock_geo_factory.return_value = mock_geo

        profiles, neighbor, other = await svc._fetch_candidates_cascade(
            my_profile=my_prof,
            my_looking_for_gender_ids=[1],
            excluded_user_ids=set(),
            desired_vibe_ids=frozenset({3}),
        )

    assert profiles == [cand]
    assert neighbor is False
    assert other is True
    # Stage 1 + Stage 2 + Stage 3 = 3 вызова.
    assert repo.find_candidates.call_count == 3
    # Третий вызов — Stage 3 без city_filter.
    stage3_kwargs = repo.find_candidates.call_args_list[2].kwargs
    assert stage3_kwargs["city_filter"] is None


@pytest.mark.asyncio
async def test_cascade_city_none_goes_directly_global() -> None:
    """city IS NULL → пропускаем Stage 1/2, сразу глобальная выдача; оба флага False."""
    my_prof = _profile(city=None, desired_vibe_id=None)
    cand = _profile(profile_id=2, user_id=2, city="Москва")

    repo = MagicMock()
    repo.find_candidates = AsyncMock(return_value=[cand])

    svc = _make_service(repo)
    profiles, neighbor, other = await svc._fetch_candidates_cascade(
        my_profile=my_prof,
        my_looking_for_gender_ids=[1],
        excluded_user_ids=set(),
        desired_vibe_ids=frozenset(),
    )
    assert profiles == [cand]
    assert neighbor is False
    assert other is False
    assert repo.find_candidates.call_count == 1
    call_kwargs = repo.find_candidates.call_args.kwargs
    assert call_kwargs["city_filter"] is None


@pytest.mark.asyncio
async def test_cascade_stage2_skipped_when_no_neighbors() -> None:
    """Если GeoService.neighbor_cities возвращает пустой список —
    Stage 2 пропускается, сразу Stage 3."""
    my_prof = _profile(city="Неизвестный", desired_vibe_id=None)
    cand = _profile(profile_id=2, user_id=2, city="Москва")

    # Stage 1 → [], Stage 3 → [cand]. Stage 2 не вызывается.
    repo = MagicMock()
    repo.find_candidates = AsyncMock(side_effect=[[], [cand]])

    svc = _make_service(repo)

    with patch("app.services.matching_service.get_geo_service") as mock_geo_factory:
        mock_geo = MagicMock()
        mock_geo.neighbor_cities.return_value = []  # нет соседей
        mock_geo_factory.return_value = mock_geo

        profiles, neighbor, other = await svc._fetch_candidates_cascade(
            my_profile=my_prof,
            my_looking_for_gender_ids=[1],
            excluded_user_ids=set(),
            desired_vibe_ids=frozenset(),
        )

    assert profiles == [cand]
    assert neighbor is False
    assert other is True
    # Только Stage 1 + Stage 3 = 2 вызова; Stage 2 пропущен.
    assert repo.find_candidates.call_count == 2


@pytest.mark.asyncio
async def test_vibe_hard_filter_passed_to_repo_when_desired_non_empty() -> None:
    """desired_vibe_ids непустой → передаётся в find_candidates как hard filter."""
    my_prof = _profile(city="Москва", desired_vibe_id=42)
    cand = _profile(profile_id=2, user_id=2, city="Москва")

    repo = MagicMock()
    repo.find_candidates = AsyncMock(return_value=[cand])

    svc = _make_service(repo)
    await svc._fetch_candidates_cascade(
        my_profile=my_prof,
        my_looking_for_gender_ids=[1],
        excluded_user_ids=set(),
        desired_vibe_ids=frozenset({42, 7}),
    )
    call_kwargs = repo.find_candidates.call_args.kwargs
    assert call_kwargs["desired_vibe_ids"] == frozenset({42, 7})


@pytest.mark.asyncio
async def test_vibe_hard_filter_empty_when_desired_is_empty() -> None:
    """desired_vibe_ids пуст → передаётся пустой frozenset в find_candidates (без фильтра)."""
    my_prof = _profile(city="Москва", desired_vibe_id=None)
    cand = _profile(profile_id=2, user_id=2, city="Москва")

    repo = MagicMock()
    repo.find_candidates = AsyncMock(return_value=[cand])

    svc = _make_service(repo)
    await svc._fetch_candidates_cascade(
        my_profile=my_prof,
        my_looking_for_gender_ids=[1],
        excluded_user_ids=set(),
        desired_vibe_ids=frozenset(),
    )
    call_kwargs = repo.find_candidates.call_args.kwargs
    assert call_kwargs["desired_vibe_ids"] == frozenset()


# ---------------------------------------------------------------------------
# desired_fandom_ids fallback в каскаде (Stage 2/3) — НЕ применяется в Stage 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cascade_stage1_does_not_pass_desired_fandom_filter() -> None:
    """Stage 1 (свой город) НЕ применяет хард-фильтр по фандомам — внутри
    своего города показываем всех релевантных, фандомы остаются мягким
    скорингом."""
    my_prof = _profile(city="Казань", desired_vibe_id=5)
    cand = _profile(profile_id=2, user_id=2, city="Казань")

    repo = MagicMock()
    repo.find_candidates = AsyncMock(return_value=[cand])

    svc = _make_service(repo)
    await svc._fetch_candidates_cascade(
        my_profile=my_prof,
        my_looking_for_gender_ids=[1],
        excluded_user_ids=set(),
        desired_vibe_ids=frozenset({5}),
        desired_fandom_ids=frozenset({10, 11}),  # юзер любит фандомы 10, 11
    )
    # Stage 1 был вызван с desired_fandom_ids=None — НИКАКОГО фильтра по фандомам.
    call_kwargs = repo.find_candidates.call_args_list[0].kwargs
    assert call_kwargs["city_filter"] == ["Казань"]
    assert call_kwargs["desired_fandom_ids"] is None


@pytest.mark.asyncio
async def test_cascade_stage2_passes_desired_fandom_filter() -> None:
    """Stage 2 (соседние города) применяет хард-фильтр по desired_fandom_ids."""
    my_prof = _profile(city="Казань", desired_vibe_id=None)
    cand = _profile(profile_id=2, user_id=2, city="Набережные Челны")

    # Stage 1 → пусто, Stage 2 → [cand].
    repo = MagicMock()
    repo.find_candidates = AsyncMock(side_effect=[[], [cand]])

    svc = _make_service(repo)

    with patch("app.services.matching_service.get_geo_service") as mock_geo_factory:
        mock_geo = MagicMock()
        mock_geo.neighbor_cities.return_value = ["Набережные Челны"]
        mock_geo_factory.return_value = mock_geo

        await svc._fetch_candidates_cascade(
            my_profile=my_prof,
            my_looking_for_gender_ids=[1],
            excluded_user_ids=set(),
            desired_vibe_ids=frozenset(),
            desired_fandom_ids=frozenset({10, 11}),
        )

    # Stage 2 = второй вызов; должен нести desired_fandom_ids=frozenset({10,11}).
    stage2_kwargs = repo.find_candidates.call_args_list[1].kwargs
    assert stage2_kwargs["city_filter"] == ["Набережные Челны"]
    assert stage2_kwargs["desired_fandom_ids"] == frozenset({10, 11})
    # А Stage 1 — без фильтра.
    stage1_kwargs = repo.find_candidates.call_args_list[0].kwargs
    assert stage1_kwargs["desired_fandom_ids"] is None


@pytest.mark.asyncio
async def test_cascade_stage3_passes_desired_fandom_filter() -> None:
    """Stage 3 (глобальная выдача) применяет хард-фильтр по desired_fandom_ids."""
    my_prof = _profile(city="Казань", desired_vibe_id=None)
    cand = _profile(profile_id=2, user_id=2, city="Владивосток")

    # Stage 1 → [], Stage 2 → [], Stage 3 → [cand].
    repo = MagicMock()
    repo.find_candidates = AsyncMock(side_effect=[[], [], [cand]])

    svc = _make_service(repo)

    with patch("app.services.matching_service.get_geo_service") as mock_geo_factory:
        mock_geo = MagicMock()
        mock_geo.neighbor_cities.return_value = ["Набережные Челны"]
        mock_geo_factory.return_value = mock_geo

        await svc._fetch_candidates_cascade(
            my_profile=my_prof,
            my_looking_for_gender_ids=[1],
            excluded_user_ids=set(),
            desired_vibe_ids=frozenset(),
            desired_fandom_ids=frozenset({42}),
        )

    stage3_kwargs = repo.find_candidates.call_args_list[2].kwargs
    assert stage3_kwargs["city_filter"] is None
    assert stage3_kwargs["desired_fandom_ids"] == frozenset({42})


@pytest.mark.asyncio
async def test_cascade_empty_desired_fandoms_disables_filter_everywhere() -> None:
    """Если у юзера desired_fandom_ids пуст — фильтр НЕ применяется ни на одном
    стейдже (передаётся None в репозиторий)."""
    my_prof = _profile(city="Казань", desired_vibe_id=None)
    cand = _profile(profile_id=2, user_id=2, city="Владивосток")

    repo = MagicMock()
    repo.find_candidates = AsyncMock(side_effect=[[], [], [cand]])

    svc = _make_service(repo)

    with patch("app.services.matching_service.get_geo_service") as mock_geo_factory:
        mock_geo = MagicMock()
        mock_geo.neighbor_cities.return_value = ["Набережные Челны"]
        mock_geo_factory.return_value = mock_geo

        await svc._fetch_candidates_cascade(
            my_profile=my_prof,
            my_looking_for_gender_ids=[1],
            excluded_user_ids=set(),
            desired_vibe_ids=frozenset(),
            desired_fandom_ids=frozenset(),  # пусто
        )

    # Все три стейджа — desired_fandom_ids=None.
    for idx in range(3):
        kwargs = repo.find_candidates.call_args_list[idx].kwargs
        assert kwargs["desired_fandom_ids"] is None, f"stage {idx + 1} should not filter fandoms"


@pytest.mark.asyncio
async def test_cascade_city_none_applies_desired_fandom_filter() -> None:
    """Если у юзера city IS NULL — сразу глобал, и квалифицированный fallback
    по фандомам применяется (как для Stage 3)."""
    my_prof = _profile(city=None, desired_vibe_id=None)
    cand = _profile(profile_id=2, user_id=2, city="Москва")

    repo = MagicMock()
    repo.find_candidates = AsyncMock(return_value=[cand])

    svc = _make_service(repo)
    await svc._fetch_candidates_cascade(
        my_profile=my_prof,
        my_looking_for_gender_ids=[1],
        excluded_user_ids=set(),
        desired_vibe_ids=frozenset(),
        desired_fandom_ids=frozenset({7}),
    )

    assert repo.find_candidates.call_count == 1
    call_kwargs = repo.find_candidates.call_args.kwargs
    assert call_kwargs["city_filter"] is None
    assert call_kwargs["desired_fandom_ids"] == frozenset({7})


# ---------------------------------------------------------------------------
# CandidateResult invariants
# ---------------------------------------------------------------------------


def test_candidate_result_defaults() -> None:
    """CandidateResult с default-флагами: оба False."""
    p = _profile()
    cr = CandidateResult(profile=p)
    assert cr.from_neighbor_city is False
    assert cr.from_other_region is False


def test_candidate_result_neighbor() -> None:
    p = _profile()
    cr = CandidateResult(profile=p, from_neighbor_city=True, from_other_region=False)
    assert cr.from_neighbor_city is True
    assert cr.from_other_region is False


def test_candidate_result_other_region() -> None:
    p = _profile()
    cr = CandidateResult(profile=p, from_neighbor_city=False, from_other_region=True)
    assert cr.from_neighbor_city is False
    assert cr.from_other_region is True
