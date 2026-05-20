"""Юнит-тесты скоринг-функции `_score_candidate` без БД.

Используем легковесный двойник Profile (`SimpleNamespace`) — нам нужны
только атрибуты `id`, `user_id`, `own_vibe_id`, `desired_vibe_id`, `created_at`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.matching_service import (
    CandidateRelations,
    MatchingWeights,
    _score_candidate,
    _vibe_match_points,
)

NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC)


def _profile(
    *,
    profile_id: int = 1,
    user_id: int = 1,
    own_vibe_id: int = 100,
    desired_vibe_id: int = 200,
    days_old: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=profile_id,
        user_id=user_id,
        own_vibe_id=own_vibe_id,
        desired_vibe_id=desired_vibe_id,
        created_at=NOW - timedelta(days=days_old),
    )


def _weights() -> MatchingWeights:
    # Берём значения, отличающиеся друг от друга — иначе перепутать слагаемые
    # в реализации просто.
    return MatchingWeights(
        w_fandom=3.0,
        w_vibe=4.0,
        w_desired_fandom=2.0,
        w_interest=1.0,
        w_recency=1.0,
    )


def test_vibe_match_two_way() -> None:
    # my.own=A, their.desired={A}; their.own=B, my.desired={B} → двустороннее.
    assert _vibe_match_points(1, frozenset({2}), 2, frozenset({1})) == 4


def test_vibe_match_one_way() -> None:
    # only my.own ∈ their.desired.
    assert _vibe_match_points(1, frozenset({99}), 5, frozenset({1})) == 2


def test_vibe_match_zero() -> None:
    assert _vibe_match_points(1, frozenset({2}), 3, frozenset({4})) == 0


def test_vibe_match_multi_desired_two_way() -> None:
    """Мульти-desired: совпадение через любой элемент набора с обеих сторон."""
    # my.own=1, my.desired={2, 5, 7}; their.own=2 (∈ my.desired), their.desired={1, 8} (1 ∈)
    assert _vibe_match_points(1, frozenset({2, 5, 7}), 2, frozenset({1, 8})) == 4


def test_vibe_match_empty_desired_means_any_and_contributes_zero() -> None:
    """Пустой desired = «любой вайб» → соответствующая сторона несовпавшая."""
    # my.desired=пусто; their.own=99 ∉ {} → b=False. their.desired={1}, my.own=1 → a=True. Итог 2.
    assert _vibe_match_points(1, frozenset(), 99, frozenset({1})) == 2
    # Оба пустые → 0.
    assert _vibe_match_points(1, frozenset(), 2, frozenset()) == 0


def test_score_zero_when_no_overlap() -> None:
    """Никаких пересечений, вайбы не сходятся → итог только recency_bonus."""
    me = _profile(profile_id=1, user_id=1, own_vibe_id=1, desired_vibe_id=2)
    them = _profile(profile_id=2, user_id=2, own_vibe_id=3, desired_vibe_id=4, days_old=0)
    result = _score_candidate(
        my_profile=me,
        my_relations=CandidateRelations(),
        their_profile=them,
        their_relations=CandidateRelations(),
        weights=_weights(),
        now=NOW,
    )
    # days=0 → recency_factor = 1.0; вклад = w_recency * 1.0 = 1.0.
    assert result.score == 1.0
    assert result.breakdown["fandom"] == 0
    assert result.breakdown["vibe"] == 0
    assert result.breakdown["desired_fandom"] == 0
    assert result.breakdown["interest"] == 0
    assert result.breakdown["recency"] == 1.0


def test_fandom_overlap_scored() -> None:
    me = _profile(profile_id=1, user_id=1, own_vibe_id=1, desired_vibe_id=2)
    them = _profile(profile_id=2, user_id=2, own_vibe_id=3, desired_vibe_id=4, days_old=0)
    my_rel = CandidateRelations(fandom_ids=frozenset({10, 20, 30, 40}))
    their_rel = CandidateRelations(fandom_ids=frozenset({10, 20, 30, 99}))
    result = _score_candidate(
        my_profile=me,
        my_relations=my_rel,
        their_profile=them,
        their_relations=their_rel,
        weights=_weights(),
        now=NOW,
    )
    # 3 общих фандома * w_fandom=3 = 9, плюс recency=1.
    assert result.breakdown["fandom"] == 9.0
    assert result.score == 10.0


def test_vibe_two_way_match_gives_4_times_w_vibe() -> None:
    me = _profile(own_vibe_id=1, desired_vibe_id=2)
    them = _profile(profile_id=2, user_id=2, own_vibe_id=2, desired_vibe_id=1, days_old=999)
    result = _score_candidate(
        my_profile=me,
        my_relations=CandidateRelations(desired_vibe_ids=frozenset({2})),
        their_profile=them,
        their_relations=CandidateRelations(desired_vibe_ids=frozenset({1})),
        weights=_weights(),
        now=NOW,
    )
    # vibe_points=4, w_vibe=4 → 16. Recency для days_old=999 ≈ 0.001.
    assert result.breakdown["vibe"] == 16.0
    assert 15.9 < result.score < 16.1


def test_vibe_one_way_match_gives_2_times_w_vibe() -> None:
    me = _profile(own_vibe_id=1, desired_vibe_id=2)
    them = _profile(profile_id=2, user_id=2, own_vibe_id=99, desired_vibe_id=1, days_old=999)
    result = _score_candidate(
        my_profile=me,
        my_relations=CandidateRelations(desired_vibe_ids=frozenset({2})),
        their_profile=them,
        their_relations=CandidateRelations(desired_vibe_ids=frozenset({1})),
        weights=_weights(),
        now=NOW,
    )
    assert result.breakdown["vibe"] == 8.0  # 2 * 4


def test_vibe_no_match_gives_zero() -> None:
    me = _profile(own_vibe_id=1, desired_vibe_id=2)
    them = _profile(profile_id=2, user_id=2, own_vibe_id=99, desired_vibe_id=88, days_old=0)
    result = _score_candidate(
        my_profile=me,
        my_relations=CandidateRelations(),
        their_profile=them,
        their_relations=CandidateRelations(),
        weights=_weights(),
        now=NOW,
    )
    assert result.breakdown["vibe"] == 0


def test_recency_bonus_higher_for_newer_profile() -> None:
    me = _profile(own_vibe_id=1, desired_vibe_id=2)
    fresh = _profile(profile_id=2, user_id=2, own_vibe_id=9, desired_vibe_id=9, days_old=0)
    old = _profile(profile_id=3, user_id=3, own_vibe_id=9, desired_vibe_id=9, days_old=30)

    fresh_score = _score_candidate(
        my_profile=me,
        my_relations=CandidateRelations(),
        their_profile=fresh,
        their_relations=CandidateRelations(),
        weights=_weights(),
        now=NOW,
    )
    old_score = _score_candidate(
        my_profile=me,
        my_relations=CandidateRelations(),
        their_profile=old,
        their_relations=CandidateRelations(),
        weights=_weights(),
        now=NOW,
    )
    assert fresh_score.breakdown["recency"] > old_score.breakdown["recency"]
    assert fresh_score.score > old_score.score


def test_desired_fandom_and_interest_overlap() -> None:
    me = _profile(own_vibe_id=1, desired_vibe_id=2)
    them = _profile(profile_id=2, user_id=2, own_vibe_id=8, desired_vibe_id=9, days_old=999)
    my_rel = CandidateRelations(
        desired_fandom_ids=frozenset({100, 200}),
        interest_ids=frozenset({1, 2, 3}),
    )
    their_rel = CandidateRelations(
        fandom_ids=frozenset({100, 200, 300}),  # пересекается c my.desired (2 шт)
        interest_ids=frozenset({2, 3, 4}),  # пересечение с моими интересами (2 шт)
    )
    result = _score_candidate(
        my_profile=me,
        my_relations=my_rel,
        their_profile=them,
        their_relations=their_rel,
        weights=_weights(),
        now=NOW,
    )
    assert result.breakdown["desired_fandom"] == 4.0  # 2 * w_desired_fandom=2
    assert result.breakdown["interest"] == 2.0  # 2 * w_interest=1
