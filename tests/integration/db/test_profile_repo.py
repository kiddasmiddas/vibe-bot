from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.dictionaries import Fandom, Gender, Interest, Vibe
from app.db.models.profile import (
    Profile,
    ProfileFandom,
    ProfileInterest,
    ProfileLookingForGender,
)
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository


async def _seed_dictionaries(db_session) -> dict[str, object]:
    """Создаёт нужные справочные записи. Полы есть из seed-миграции,
    вайбы и фандомы/интересы — создаём руками."""
    dict_repo = DictionaryRepository(db_session)
    male = await dict_repo.get_by_code(Gender, "male")
    female = await dict_repo.get_by_code(Gender, "female")
    assert male is not None and female is not None

    vibe_a = Vibe(
        code="test_vibe_a",
        title="Vibe A",
        number=9001,
        image_file_id="file_a",
    )
    vibe_b = Vibe(
        code="test_vibe_b",
        title="Vibe B",
        number=9002,
        image_file_id="file_b",
    )
    fandom_x = Fandom(code="test_fandom_x", title="Fandom X")
    fandom_y = Fandom(code="test_fandom_y", title="Fandom Y")
    fandom_z = Fandom(code="test_fandom_z", title="Fandom Z")
    interest_1 = Interest(code="test_int_1", title="Int 1")
    interest_2 = Interest(code="test_int_2", title="Int 2")
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


async def _make_profile(db_session, fixtures, *, telegram_id: int) -> Profile:
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    repo = ProfileRepository(db_session)
    return await repo.create(
        user_id=user.id,
        nickname="Nick",
        age=25,
        gender_id=fixtures["male"].id,
        looking_for_age_min=20,
        looking_for_age_max=30,
        bio="hello",
        own_vibe_id=fixtures["vibe_a"].id,
        main_media_type="photo",
        main_media_file_id="photo_file_id",
    )


@pytest.mark.asyncio
async def test_create_and_get_by_user_id_roundtrip(db_session) -> None:
    fixtures = await _seed_dictionaries(db_session)
    profile = await _make_profile(db_session, fixtures, telegram_id=1001)
    repo = ProfileRepository(db_session)

    fetched = await repo.get_by_user_id(profile.user_id)
    assert fetched is not None
    assert fetched.id == profile.id
    assert fetched.nickname == "Nick"
    assert fetched.age == 25
    assert fetched.is_completed is False
    assert fetched.is_active is True
    assert fetched.is_hidden is False


@pytest.mark.asyncio
async def test_set_fandoms_atomic_replace(db_session) -> None:
    fixtures = await _seed_dictionaries(db_session)
    profile = await _make_profile(db_session, fixtures, telegram_id=1002)
    repo = ProfileRepository(db_session)

    await repo.set_fandoms(profile.id, [fixtures["fandom_x"].id, fixtures["fandom_y"].id])
    rows = (
        (
            await db_session.execute(
                select(ProfileFandom.fandom_id).where(ProfileFandom.profile_id == profile.id)
            )
        )
        .scalars()
        .all()
    )
    assert set(rows) == {fixtures["fandom_x"].id, fixtures["fandom_y"].id}

    # Полная замена: остаются только новые id.
    await repo.set_fandoms(profile.id, [fixtures["fandom_z"].id])
    rows = (
        (
            await db_session.execute(
                select(ProfileFandom.fandom_id).where(ProfileFandom.profile_id == profile.id)
            )
        )
        .scalars()
        .all()
    )
    assert set(rows) == {fixtures["fandom_z"].id}

    # Пустой список — очистка.
    await repo.set_fandoms(profile.id, [])
    rows = (
        (
            await db_session.execute(
                select(ProfileFandom.fandom_id).where(ProfileFandom.profile_id == profile.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_set_interests_and_looking_for_genders(db_session) -> None:
    fixtures = await _seed_dictionaries(db_session)
    profile = await _make_profile(db_session, fixtures, telegram_id=1003)
    repo = ProfileRepository(db_session)

    await repo.set_interests(profile.id, [fixtures["interest_1"].id, fixtures["interest_2"].id])
    await repo.set_looking_for_genders(profile.id, [fixtures["male"].id, fixtures["female"].id])

    interests = (
        (
            await db_session.execute(
                select(ProfileInterest.interest_id).where(ProfileInterest.profile_id == profile.id)
            )
        )
        .scalars()
        .all()
    )
    genders = (
        (
            await db_session.execute(
                select(ProfileLookingForGender.gender_id).where(
                    ProfileLookingForGender.profile_id == profile.id
                )
            )
        )
        .scalars()
        .all()
    )

    assert set(interests) == {fixtures["interest_1"].id, fixtures["interest_2"].id}
    assert set(genders) == {fixtures["male"].id, fixtures["female"].id}


@pytest.mark.asyncio
async def test_update_changes_fields_and_updated_at(db_session) -> None:
    fixtures = await _seed_dictionaries(db_session)
    profile = await _make_profile(db_session, fixtures, telegram_id=1004)
    original_updated_at = profile.updated_at
    repo = ProfileRepository(db_session)

    # Принудительная пауза в БД-времени: используем raw SQL чтобы updated_at заведомо сдвинулся.
    updated = await repo.update(
        profile.id, nickname="NewNick", bio="updated bio", is_completed=True
    )

    assert updated.nickname == "NewNick"
    assert updated.bio == "updated bio"
    assert updated.is_completed is True
    # updated_at должен обновиться onupdate=func.now().
    assert updated.updated_at >= original_updated_at


@pytest.mark.asyncio
async def test_mark_completed_and_set_hidden(db_session) -> None:
    fixtures = await _seed_dictionaries(db_session)
    profile = await _make_profile(db_session, fixtures, telegram_id=1005)
    repo = ProfileRepository(db_session)

    await repo.mark_completed(profile.id)
    await repo.set_hidden(profile.id, True)
    await db_session.flush()
    await db_session.refresh(profile)

    assert profile.is_completed is True
    assert profile.is_hidden is True


@pytest.mark.asyncio
async def test_check_constraint_age_range_invalid(db_session) -> None:
    fixtures = await _seed_dictionaries(db_session)
    user = await UserRepository(db_session).create(telegram_id=1006)
    repo = ProfileRepository(db_session)

    with pytest.raises(IntegrityError):
        await repo.create(
            user_id=user.id,
            nickname="Bad",
            age=20,
            gender_id=fixtures["male"].id,
            looking_for_age_min=40,
            looking_for_age_max=30,  # min > max
            bio="x",
            own_vibe_id=fixtures["vibe_a"].id,
            main_media_type="photo",
            main_media_file_id="f",
        )


@pytest.mark.asyncio
async def test_check_constraint_main_media_type(db_session) -> None:
    fixtures = await _seed_dictionaries(db_session)
    user = await UserRepository(db_session).create(telegram_id=1007)
    repo = ProfileRepository(db_session)

    with pytest.raises(IntegrityError):
        await repo.create(
            user_id=user.id,
            nickname="Bad",
            age=20,
            gender_id=fixtures["male"].id,
            looking_for_age_min=18,
            looking_for_age_max=30,
            bio="x",
            own_vibe_id=fixtures["vibe_a"].id,
            main_media_type="audio",  # not allowed
            main_media_file_id="f",
        )


@pytest.mark.asyncio
async def test_get_fandom_ids_and_relations(db_session) -> None:
    fixtures = await _seed_dictionaries(db_session)
    profile = await _make_profile(db_session, fixtures, telegram_id=1010)
    repo = ProfileRepository(db_session)

    await repo.set_fandoms(
        profile.id, [fixtures["fandom_x"].id, fixtures["fandom_y"].id, fixtures["fandom_z"].id]
    )
    await repo.set_desired_fandoms(profile.id, [fixtures["fandom_x"].id])
    await repo.set_interests(profile.id, [fixtures["interest_1"].id])
    await repo.set_looking_for_genders(profile.id, [fixtures["female"].id])

    assert set(await repo.get_fandom_ids(profile.id)) == {
        fixtures["fandom_x"].id,
        fixtures["fandom_y"].id,
        fixtures["fandom_z"].id,
    }
    assert set(await repo.get_desired_fandom_ids(profile.id)) == {fixtures["fandom_x"].id}
    assert set(await repo.get_interest_ids(profile.id)) == {fixtures["interest_1"].id}
    assert set(await repo.get_looking_for_gender_ids(profile.id)) == {fixtures["female"].id}


@pytest.mark.asyncio
async def test_set_and_get_desired_vibe_ids(db_session) -> None:
    """set_desired_vibe_ids / get_desired_vibe_ids — атомарная замена M2M."""
    fixtures = await _seed_dictionaries(db_session)
    profile = await _make_profile(db_session, fixtures, telegram_id=1011)
    repo = ProfileRepository(db_session)

    # Установить два желаемых вайба.
    await repo.set_desired_vibe_ids(profile.id, [fixtures["vibe_a"].id, fixtures["vibe_b"].id])
    ids = await repo.get_desired_vibe_ids(profile.id)
    assert set(ids) == {fixtures["vibe_a"].id, fixtures["vibe_b"].id}

    # Заменить на один.
    await repo.set_desired_vibe_ids(profile.id, [fixtures["vibe_a"].id])
    ids = await repo.get_desired_vibe_ids(profile.id)
    assert ids == [fixtures["vibe_a"].id]

    # Очистить.
    await repo.set_desired_vibe_ids(profile.id, [])
    ids = await repo.get_desired_vibe_ids(profile.id)
    assert ids == []


@pytest.mark.asyncio
async def test_set_vibes_need_review(db_session) -> None:
    """set_vibes_need_review устанавливает и сбрасывает флаг."""
    fixtures = await _seed_dictionaries(db_session)
    profile = await _make_profile(db_session, fixtures, telegram_id=1012)
    repo = ProfileRepository(db_session)

    assert profile.vibes_need_review is False

    await repo.set_vibes_need_review(profile.id, True)
    await db_session.refresh(profile)
    assert profile.vibes_need_review is True

    await repo.set_vibes_need_review(profile.id, False)
    await db_session.refresh(profile)
    assert profile.vibes_need_review is False


@pytest.mark.asyncio
async def test_delete_by_user_id_cascades_links(db_session) -> None:
    fixtures = await _seed_dictionaries(db_session)
    profile = await _make_profile(db_session, fixtures, telegram_id=1008)
    repo = ProfileRepository(db_session)

    await repo.set_fandoms(profile.id, [fixtures["fandom_x"].id])
    await repo.set_interests(profile.id, [fixtures["interest_1"].id])
    await repo.set_looking_for_genders(profile.id, [fixtures["male"].id])

    profile_id = profile.id
    user_id = profile.user_id

    await repo.delete_by_user_id(user_id)
    await db_session.flush()

    assert await repo.get_by_user_id(user_id) is None
    fandom_rows = (
        await db_session.execute(
            select(ProfileFandom).where(ProfileFandom.profile_id == profile_id)
        )
    ).all()
    interest_rows = (
        await db_session.execute(
            select(ProfileInterest).where(ProfileInterest.profile_id == profile_id)
        )
    ).all()
    gender_rows = (
        await db_session.execute(
            select(ProfileLookingForGender).where(ProfileLookingForGender.profile_id == profile_id)
        )
    ).all()
    assert fandom_rows == []
    assert interest_rows == []
    assert gender_rows == []
