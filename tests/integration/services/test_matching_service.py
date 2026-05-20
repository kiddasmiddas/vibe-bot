"""Интеграционные тесты `MatchingService.get_next_candidates` против реальной БД.

Используют сессионный `db_session` с автооткатом (см. conftest.py).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select as _select

from app.db.models.dictionaries import Fandom, Gender, Interest, Vibe
from app.db.models.matching import Like, Match
from app.db.models.profile import Profile
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.db.repositories.user_repo import UserRepository
from app.services.matching_service import MatchingService


async def _seed_fixtures(db_session) -> dict[str, Any]:
    dict_repo = DictionaryRepository(db_session)
    male = await dict_repo.get_by_code(Gender, "male")
    female = await dict_repo.get_by_code(Gender, "female")
    assert male is not None and female is not None

    vibe_a = Vibe(code="ms_vibe_a", title="A", number=11001, image_file_id="fa")
    vibe_b = Vibe(code="ms_vibe_b", title="B", number=11002, image_file_id="fb")
    fandom_x = Fandom(code="ms_fandom_x", title="X")
    fandom_y = Fandom(code="ms_fandom_y", title="Y")
    fandom_z = Fandom(code="ms_fandom_z", title="Z")
    interest_1 = Interest(code="ms_int_1", title="I1")
    interest_2 = Interest(code="ms_int_2", title="I2")
    db_session.add_all([vibe_a, vibe_b, fandom_x, fandom_y, fandom_z, interest_1, interest_2])
    await db_session.flush()

    return {
        "male": male,
        "female": female,
        "vibe_a": vibe_a,
        "vibe_b": vibe_b,
        "fandom_x": fandom_x,
        "fandom_y": fandom_y,
        "fandom_z": fandom_z,
        "interest_1": interest_1,
        "interest_2": interest_2,
    }


async def _make_user_with_profile(
    db_session,
    *,
    telegram_id: int,
    gender_id: int,
    looking_for_gender_ids: list[int],
    age: int = 25,
    looking_for_age_min: int = 18,
    looking_for_age_max: int = 60,
    own_vibe_id: int,
    desired_vibe_ids: list[int] | None = None,
    city: str | None = None,
    fandom_ids: list[int] | None = None,
    desired_fandom_ids: list[int] | None = None,
    interest_ids: list[int] | None = None,
    is_active: bool = True,
    is_hidden: bool = False,
    is_completed: bool = True,
    is_pending_review: bool = False,
) -> Profile:
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    repo = ProfileRepository(db_session)
    profile = await repo.create(
        user_id=user.id,
        nickname=f"User{telegram_id}",
        age=age,
        gender_id=gender_id,
        looking_for_age_min=looking_for_age_min,
        looking_for_age_max=looking_for_age_max,
        bio="bio",
        city=city,
        own_vibe_id=own_vibe_id,
        main_media_type="photo",
        main_media_file_id="file",
        is_active=is_active,
        is_hidden=is_hidden,
        is_completed=is_completed,
        is_pending_review=is_pending_review,
    )
    await repo.set_looking_for_genders(profile.id, looking_for_gender_ids)
    if desired_vibe_ids is not None:
        await repo.set_desired_vibe_ids(profile.id, desired_vibe_ids)
    if fandom_ids:
        await repo.set_fandoms(profile.id, fandom_ids)
    if desired_fandom_ids:
        await repo.set_desired_fandoms(profile.id, desired_fandom_ids)
    if interest_ids:
        await repo.set_interests(profile.id, interest_ids)
    return profile


def _service(db_session) -> MatchingService:
    return MatchingService(
        profile_repo=ProfileRepository(db_session),
        matching_repo=MatchingRepository(db_session),
        settings_repo=SettingsRepository(db_session),
        dictionary_repo=DictionaryRepository(db_session),
        user_repo=UserRepository(db_session),
        session=db_session,
    )


@pytest.mark.asyncio
async def test_returns_empty_when_no_own_profile(db_session) -> None:
    user = await UserRepository(db_session).create(telegram_id=30001)
    result = await _service(db_session).get_next_candidates(user.id)
    assert result == []


@pytest.mark.asyncio
async def test_get_next_candidates_filters_self(db_session) -> None:
    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30010,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["male"].id, fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    result = await _service(db_session).get_next_candidates(me.user_id)
    assert me.user_id not in {p.profile.user_id for p in result}


@pytest.mark.asyncio
async def test_filters_by_gender_compatibility(db_session) -> None:
    fx = await _seed_fixtures(db_session)
    # Я мужчина, ищу женщин.
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30020,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    # Несовместимый кандидат №1: мужчина — мне не подходит по полу.
    await _make_user_with_profile(
        db_session,
        telegram_id=30021,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["male"].id, fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    # Несовместимый №2: женщина, но ищет только женщин — я ей не подхожу.
    await _make_user_with_profile(
        db_session,
        telegram_id=30022,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    # Совместимая: женщина, ищет мужчин.
    ok = await _make_user_with_profile(
        db_session,
        telegram_id=30023,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )

    result = await _service(db_session).get_next_candidates(me.user_id)
    user_ids = {p.profile.user_id for p in result}
    assert user_ids == {ok.user_id}


@pytest.mark.asyncio
async def test_filters_by_age_range(db_session) -> None:
    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30030,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        age=25,
        looking_for_age_min=20,
        looking_for_age_max=30,
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    # Слишком молодая — вне моего диапазона.
    await _make_user_with_profile(
        db_session,
        telegram_id=30031,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        age=18,
        looking_for_age_min=18,
        looking_for_age_max=99,
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    # Я не попадаю в её диапазон (она ищет 35–40).
    await _make_user_with_profile(
        db_session,
        telegram_id=30032,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        age=25,
        looking_for_age_min=35,
        looking_for_age_max=40,
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    # Подходит обоим.
    ok = await _make_user_with_profile(
        db_session,
        telegram_id=30033,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        age=25,
        looking_for_age_min=20,
        looking_for_age_max=30,
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )

    result = await _service(db_session).get_next_candidates(me.user_id)
    assert {p.profile.user_id for p in result} == {ok.user_id}


@pytest.mark.asyncio
async def test_filters_pending_review_hidden_inactive(db_session) -> None:
    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30040,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    await _make_user_with_profile(
        db_session,
        telegram_id=30041,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        is_pending_review=True,
    )
    await _make_user_with_profile(
        db_session,
        telegram_id=30042,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        is_hidden=True,
    )
    await _make_user_with_profile(
        db_session,
        telegram_id=30043,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        is_active=False,
    )
    await _make_user_with_profile(
        db_session,
        telegram_id=30044,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        is_completed=False,
    )
    ok = await _make_user_with_profile(
        db_session,
        telegram_id=30045,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )

    result = await _service(db_session).get_next_candidates(me.user_id)
    assert {p.profile.user_id for p in result} == {ok.user_id}


@pytest.mark.asyncio
async def test_filters_excluded_via_block(db_session) -> None:
    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30050,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    blocked = await _make_user_with_profile(
        db_session,
        telegram_id=30051,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    other = await _make_user_with_profile(
        db_session,
        telegram_id=30052,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    await MatchingRepository(db_session).add_block(me.user_id, blocked.user_id)
    await db_session.flush()

    result = await _service(db_session).get_next_candidates(me.user_id)
    user_ids = {p.profile.user_id for p in result}
    assert blocked.user_id not in user_ids
    assert other.user_id in user_ids


@pytest.mark.asyncio
async def test_hard_vibe_filter_by_desired_vibe(db_session) -> None:
    """Хард-фильтр: показываем только тех, чей own_vibe == мой desired_vibe."""
    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30080,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],  # ищу тех, у кого own_vibe == vibe_a
    )
    # Совпадает по вайбу: own_vibe == vibe_a.
    ok = await _make_user_with_profile(
        db_session,
        telegram_id=30081,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    # Не совпадает: own_vibe == vibe_b → отфильтрован.
    await _make_user_with_profile(
        db_session,
        telegram_id=30082,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_b"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    result = await _service(db_session).get_next_candidates(me.user_id)
    assert {p.profile.user_id for p in result} == {ok.user_id}


@pytest.mark.asyncio
async def test_null_desired_vibe_disables_vibe_filter(db_session) -> None:
    """desired_vibe_ids=[] («любой вайб») → хард-фильтр по вайбу выключен."""
    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30090,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[],  # любой вайб
    )
    a = await _make_user_with_profile(
        db_session,
        telegram_id=30091,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    b = await _make_user_with_profile(
        db_session,
        telegram_id=30092,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_b"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    result = await _service(db_session).get_next_candidates(me.user_id)
    assert {p.profile.user_id for p in result} == {a.user_id, b.user_id}


@pytest.mark.asyncio
async def test_city_filter_prefers_same_city(db_session) -> None:
    """Stage 1 каскада: при наличии кандидатов в своём городе глобальная
    выдача не задействуется — далёкий город в результат не попадает."""
    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30100,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        city="Москва",
    )
    same_city = await _make_user_with_profile(
        db_session,
        telegram_id=30101,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        city="Москва",
    )
    # Далёкий город — в Stage 1 не попадает, Stage 3 не запускается.
    await _make_user_with_profile(
        db_session,
        telegram_id=30102,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        city="Владивосток",
    )
    result = await _service(db_session).get_next_candidates(me.user_id)
    assert {p.profile.user_id for p in result} == {same_city.user_id}
    assert all(not p.from_neighbor_city and not p.from_other_region for p in result)


@pytest.mark.asyncio
async def test_city_null_searcher_sees_all_cities(db_session) -> None:
    """У искателя city IS NULL — фильтр по городу выключен, виден любой город."""
    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30110,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        city=None,
    )
    msk = await _make_user_with_profile(
        db_session,
        telegram_id=30111,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        city="Москва",
    )
    vvo = await _make_user_with_profile(
        db_session,
        telegram_id=30112,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        city="Владивосток",
    )
    result = await _service(db_session).get_next_candidates(me.user_id)
    assert {p.profile.user_id for p in result} == {msk.user_id, vvo.user_id}


@pytest.mark.asyncio
async def test_orders_by_score(db_session) -> None:
    """Три совместимых кандидата с разным числом совпадающих фандомов.
    Чем больше совпадений — тем выше в выдаче."""
    fx = await _seed_fixtures(db_session)
    fandoms = [fx["fandom_x"].id, fx["fandom_y"].id, fx["fandom_z"].id]

    me = await _make_user_with_profile(
        db_session,
        telegram_id=30060,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        fandom_ids=fandoms,
    )
    low = await _make_user_with_profile(
        db_session,
        telegram_id=30061,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        fandom_ids=[fandoms[0]],
    )
    mid = await _make_user_with_profile(
        db_session,
        telegram_id=30062,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        fandom_ids=fandoms[:2],
    )
    high = await _make_user_with_profile(
        db_session,
        telegram_id=30063,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        fandom_ids=fandoms,
    )

    result = await _service(db_session).get_next_candidates(me.user_id)
    ordered_ids = [p.profile.user_id for p in result]
    assert ordered_ids.index(high.user_id) < ordered_ids.index(mid.user_id)
    assert ordered_ids.index(mid.user_id) < ordered_ids.index(low.user_id)


@pytest.mark.asyncio
async def test_weights_read_from_settings_change_behavior(db_session) -> None:
    """Поменяв w_fandom через SettingsRepository, мы должны увидеть другой порядок."""
    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30070,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        fandom_ids=[fx["fandom_x"].id, fx["fandom_y"].id],
        interest_ids=[fx["interest_1"].id, fx["interest_2"].id],
    )
    # A: совпадает 2 фандома, 0 интересов.
    a = await _make_user_with_profile(
        db_session,
        telegram_id=30071,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        fandom_ids=[fx["fandom_x"].id, fx["fandom_y"].id],
    )
    # B: 0 фандомов, 2 интереса.
    b = await _make_user_with_profile(
        db_session,
        telegram_id=30072,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
        interest_ids=[fx["interest_1"].id, fx["interest_2"].id],
    )

    settings_repo = SettingsRepository(db_session)
    # Дефолты из seed: w_fandom=3, w_interest=1 → A (6) > B (2).
    result_default = await _service(db_session).get_next_candidates(me.user_id)
    ids_default = [p.profile.user_id for p in result_default]
    assert ids_default.index(a.user_id) < ids_default.index(b.user_id)

    # Меняем веса: интересы стали гораздо ценнее фандомов.
    await settings_repo.set("match_w_fandom", "1")
    await settings_repo.set("match_w_interest", "100")
    await db_session.flush()

    result_changed = await _service(db_session).get_next_candidates(me.user_id)
    ids_changed = [p.profile.user_id for p in result_changed]
    assert ids_changed.index(b.user_id) < ids_changed.index(a.user_id)


# --------------------------- 4.3: process_like ---------------------------


async def _two_users(db_session, *, ta: int, tb: int):
    user_a = await UserRepository(db_session).create(telegram_id=ta)
    user_b = await UserRepository(db_session).create(telegram_id=tb)
    return user_a, user_b


@pytest.mark.asyncio
async def test_view_cooldown_filters_recently_viewed(db_session) -> None:
    """Просмотренная анкета не должна возвращаться повторно в течение cooldown."""
    from app.db.repositories.matching_repo import MatchingRepository

    fx = await _seed_fixtures(db_session)
    me = await _make_user_with_profile(
        db_session,
        telegram_id=30900,
        gender_id=fx["male"].id,
        looking_for_gender_ids=[fx["female"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    target = await _make_user_with_profile(
        db_session,
        telegram_id=30901,
        gender_id=fx["female"].id,
        looking_for_gender_ids=[fx["male"].id],
        own_vibe_id=fx["vibe_a"].id,
        desired_vibe_ids=[fx["vibe_a"].id],
    )
    # Видим её до просмотра.
    before = await _service(db_session).get_next_candidates(me.user_id)
    assert target.user_id in {p.profile.user_id for p in before}

    # Помечаем как просмотренную → исключается из выдачи (default cooldown 14 дней).
    await MatchingRepository(db_session).add_viewed(viewer_id=me.user_id, target_id=target.user_id)
    await db_session.flush()
    after = await _service(db_session).get_next_candidates(me.user_id)
    assert target.user_id not in {p.profile.user_id for p in after}


@pytest.mark.asyncio
async def test_process_like_records_like(db_session) -> None:
    user_a, user_b = await _two_users(db_session, ta=40001, tb=40002)
    outcome = await _service(db_session).process_like(
        from_user_id=user_a.id, to_user_id=user_b.id, kind="like"
    )
    assert outcome.like_recorded is True
    assert outcome.match_created is False
    assert outcome.match_id is None

    likes = list(
        (
            await db_session.execute(
                _select(Like).where(Like.from_user_id == user_a.id, Like.to_user_id == user_b.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(likes) == 1


@pytest.mark.asyncio
async def test_process_like_creates_match_on_reciprocal(db_session) -> None:
    user_a, user_b = await _two_users(db_session, ta=40010, tb=40011)
    # A → B
    await _service(db_session).process_like(
        from_user_id=user_a.id, to_user_id=user_b.id, kind="like"
    )
    # B → A: должно создать матч.
    outcome = await _service(db_session).process_like(
        from_user_id=user_b.id, to_user_id=user_a.id, kind="like"
    )
    assert outcome.like_recorded is True
    assert outcome.match_created is True
    assert outcome.match_id is not None
    assert outcome.other_user_telegram_id == user_a.telegram_id


@pytest.mark.asyncio
async def test_process_like_duplicate_no_error(db_session) -> None:
    user_a, user_b = await _two_users(db_session, ta=40020, tb=40021)
    first = await _service(db_session).process_like(
        from_user_id=user_a.id, to_user_id=user_b.id, kind="like"
    )
    assert first.like_recorded is True
    dup = await _service(db_session).process_like(
        from_user_id=user_a.id, to_user_id=user_b.id, kind="like"
    )
    assert dup.like_recorded is False
    assert dup.match_created is False
    assert dup.match_id is None


@pytest.mark.asyncio
async def test_initial_message_priority_from_my_superlike(db_session) -> None:
    """Я superlike с msg → B обычный лайк → но т.к. B лайкнул первым (reciprocal),
    то у меня нет reciprocal со стороны B на момент superlike — я первый.
    Поэтому B лайкает вторым и создаёт мэтч. Reciprocal у B — мой superlike.
    initial_message == мой msg."""
    user_a, user_b = await _two_users(db_session, ta=40030, tb=40031)
    await _service(db_session).process_like(
        from_user_id=user_a.id,
        to_user_id=user_b.id,
        kind="superlike",
        message="hello from A",
    )
    outcome = await _service(db_session).process_like(
        from_user_id=user_b.id, to_user_id=user_a.id, kind="like"
    )
    assert outcome.match_created is True
    assert outcome.initial_message == "hello from A"


@pytest.mark.asyncio
async def test_initial_message_from_reciprocal_superlike(db_session) -> None:
    """A обычный → B superlike → match. reciprocal (A) — обычный лайк, мой (B) —
    superlike → initial_message = B's message."""
    user_a, user_b = await _two_users(db_session, ta=40040, tb=40041)
    await _service(db_session).process_like(
        from_user_id=user_a.id, to_user_id=user_b.id, kind="like"
    )
    outcome = await _service(db_session).process_like(
        from_user_id=user_b.id,
        to_user_id=user_a.id,
        kind="superlike",
        message="hello from B",
    )
    assert outcome.match_created is True
    assert outcome.initial_message == "hello from B"


@pytest.mark.asyncio
async def test_match_user_a_b_ordered(db_session) -> None:
    """Match создаётся с user_a_id < user_b_id независимо от порядка лайков."""
    user_a, user_b = await _two_users(db_session, ta=40050, tb=40051)
    lower, higher = sorted([user_a.id, user_b.id])
    # Лайк от higher к lower сначала, потом от lower — закрытие.
    await _service(db_session).process_like(from_user_id=higher, to_user_id=lower, kind="like")
    outcome = await _service(db_session).process_like(
        from_user_id=lower, to_user_id=higher, kind="like"
    )
    assert outcome.match_created is True
    match = (
        await db_session.execute(_select(Match).where(Match.id == outcome.match_id))
    ).scalar_one()
    assert match.user_a_id == lower
    assert match.user_b_id == higher
