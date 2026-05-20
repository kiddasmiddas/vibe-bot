from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db.models.matching import Block, Dislike, Like, Match, ViewedProfile
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.user_repo import UserRepository


async def _make_user(db_session, telegram_id: int) -> int:
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    return user.id


@pytest.mark.asyncio
async def test_add_like_and_has_reciprocal(db_session) -> None:
    a = await _make_user(db_session, 20001)
    b = await _make_user(db_session, 20002)
    repo = MatchingRepository(db_session)

    await repo.add_like(b, a, kind="like")
    reciprocal = await repo.has_reciprocal_like(from_user_id=a, to_user_id=b)
    assert reciprocal is not None
    assert reciprocal.from_user_id == b
    assert reciprocal.to_user_id == a

    # Никаких встречных лайков в обратную сторону нет.
    assert await repo.has_reciprocal_like(from_user_id=b, to_user_id=a) is None


@pytest.mark.asyncio
async def test_add_like_duplicate_raises(db_session) -> None:
    a = await _make_user(db_session, 20003)
    b = await _make_user(db_session, 20004)
    repo = MatchingRepository(db_session)

    await repo.add_like(a, b, kind="like")
    with pytest.raises(IntegrityError):
        await repo.add_like(a, b, kind="like")


@pytest.mark.asyncio
async def test_self_like_violates_check(db_session) -> None:
    a = await _make_user(db_session, 20005)
    repo = MatchingRepository(db_session)
    with pytest.raises(IntegrityError):
        await repo.add_like(a, a, kind="like")


@pytest.mark.asyncio
async def test_invalid_kind_violates_check(db_session) -> None:
    a = await _make_user(db_session, 20006)
    b = await _make_user(db_session, 20007)
    repo = MatchingRepository(db_session)
    with pytest.raises(IntegrityError):
        await repo.add_like(a, b, kind="haha")


@pytest.mark.asyncio
async def test_create_match_reorders_user_a_lt_b(db_session) -> None:
    a = await _make_user(db_session, 20010)
    b = await _make_user(db_session, 20011)
    repo = MatchingRepository(db_session)

    # Передаём в обратном порядке: (b, a) при b > a — репозиторий должен переставить.
    bigger, smaller = (b, a) if b > a else (a, b)
    match = await repo.create_match(bigger, smaller, initial_message="hi")
    assert match.user_a_id < match.user_b_id
    assert {match.user_a_id, match.user_b_id} == {a, b}
    assert match.initial_message == "hi"


@pytest.mark.asyncio
async def test_create_match_unordered_check_constraint(db_session) -> None:
    """Если кто-то вручную вставит Match с user_a > user_b — БД должна отказать."""
    a = await _make_user(db_session, 20012)
    b = await _make_user(db_session, 20013)
    smaller, bigger = sorted([a, b])

    # Прямой insert с нарушенным порядком.
    bad_match = Match(user_a_id=bigger, user_b_id=smaller)
    db_session.add(bad_match)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_list_matches_for_user_both_positions(db_session) -> None:
    a = await _make_user(db_session, 20020)
    b = await _make_user(db_session, 20021)
    c = await _make_user(db_session, 20022)
    repo = MatchingRepository(db_session)

    await repo.create_match(a, b)
    await repo.create_match(a, c)
    await db_session.flush()

    matches_a = await repo.list_matches_for_user(a)
    matches_b = await repo.list_matches_for_user(b)
    matches_c = await repo.list_matches_for_user(c)

    assert len(matches_a) == 2
    assert len(matches_b) == 1
    assert len(matches_c) == 1
    # b и c пересекаются с a в разных позициях user_a/user_b.
    pair_b = {matches_b[0].user_a_id, matches_b[0].user_b_id}
    pair_c = {matches_c[0].user_a_id, matches_c[0].user_b_id}
    assert pair_b == {a, b}
    assert pair_c == {a, c}


@pytest.mark.asyncio
async def test_add_viewed_upsert_updates_viewed_at(db_session) -> None:
    viewer = await _make_user(db_session, 20030)
    target = await _make_user(db_session, 20031)
    repo = MatchingRepository(db_session)

    await repo.add_viewed(viewer, target)
    row1 = (
        await db_session.execute(
            select(ViewedProfile).where(
                ViewedProfile.viewer_user_id == viewer,
                ViewedProfile.target_user_id == target,
            )
        )
    ).scalar_one()
    first_seen = row1.viewed_at

    # Принудительно состарим запись, чтобы заметить, что upsert именно обновляет viewed_at.
    await db_session.execute(
        update(ViewedProfile)
        .where(
            ViewedProfile.viewer_user_id == viewer,
            ViewedProfile.target_user_id == target,
        )
        .values(viewed_at=first_seen - timedelta(days=10))
    )
    await db_session.flush()

    # Повторный вызов не должен падать и должен обновить viewed_at до now().
    await repo.add_viewed(viewer, target)
    db_session.expire_all()
    row2 = (
        await db_session.execute(
            select(ViewedProfile).where(
                ViewedProfile.viewer_user_id == viewer,
                ViewedProfile.target_user_id == target,
            )
        )
    ).scalar_one()
    # После upsert viewed_at должен быть свежее, чем искусственно состаренное значение.
    assert row2.viewed_at > first_seen - timedelta(days=5)


@pytest.mark.asyncio
async def test_get_excluded_user_ids_collects_all_sources(db_session) -> None:
    me = await _make_user(db_session, 20040)
    liked = await _make_user(db_session, 20041)
    disliked = await _make_user(db_session, 20042)
    blocked_by_me = await _make_user(db_session, 20043)
    blocked_me = await _make_user(db_session, 20044)
    viewed_recent = await _make_user(db_session, 20045)
    viewed_old = await _make_user(db_session, 20046)
    fresh = await _make_user(db_session, 20047)

    repo = MatchingRepository(db_session)
    await repo.add_like(me, liked, kind="like")
    await repo.add_dislike(me, disliked)
    await repo.add_block(me, blocked_by_me)
    await repo.add_block(blocked_me, me)
    await repo.add_viewed(me, viewed_recent)
    await repo.add_viewed(me, viewed_old)

    # Делаем "старый" просмотр действительно старым — выходит за пределы cooldown'а.
    await db_session.execute(
        update(ViewedProfile)
        .where(
            ViewedProfile.viewer_user_id == me,
            ViewedProfile.target_user_id == viewed_old,
        )
        .values(viewed_at=datetime.now(tz=UTC) - timedelta(days=30))
    )
    await db_session.flush()

    excluded = await repo.get_excluded_user_ids(me)

    assert me in excluded
    assert liked in excluded
    assert disliked in excluded
    assert blocked_by_me in excluded
    assert blocked_me in excluded
    assert viewed_recent in excluded
    # Старый просмотр и не пересекавшийся пользователь — не исключены.
    assert viewed_old not in excluded
    assert fresh not in excluded


@pytest.mark.asyncio
async def test_list_incoming_likes_filters_answered(db_session) -> None:
    me = await _make_user(db_session, 20050)
    pending = await _make_user(db_session, 20051)
    liked_back = await _make_user(db_session, 20052)
    disliked_back = await _make_user(db_session, 20053)
    matched_with = await _make_user(db_session, 20054)

    repo = MatchingRepository(db_session)
    # Все четверо лайкнули меня.
    await repo.add_like(pending, me, kind="like")
    await repo.add_like(liked_back, me, kind="like")
    await repo.add_like(disliked_back, me, kind="like")
    await repo.add_like(matched_with, me, kind="like")

    # На троих из них я уже отреагировал.
    await repo.add_like(me, liked_back, kind="like")
    await repo.add_dislike(me, disliked_back)
    await repo.create_match(me, matched_with)
    await db_session.flush()

    incoming = await repo.list_incoming_likes(me)
    from_ids = {like.from_user_id for like in incoming}
    assert from_ids == {pending}


@pytest.mark.asyncio
async def test_list_incoming_likes_excludes_blocked(db_session) -> None:
    """Если я заблокировал автора лайка — лайк не должен возвращаться.
    То же и в обратную сторону: если он заблокировал меня — тоже скрыть."""
    me = await _make_user(db_session, 20060)
    i_blocked = await _make_user(db_session, 20061)
    blocked_me = await _make_user(db_session, 20062)
    fresh = await _make_user(db_session, 20063)

    repo = MatchingRepository(db_session)
    await repo.add_like(i_blocked, me, kind="like")
    await repo.add_like(blocked_me, me, kind="like")
    await repo.add_like(fresh, me, kind="like")
    await repo.add_block(blocker_id=me, blocked_id=i_blocked)
    await repo.add_block(blocker_id=blocked_me, blocked_id=me)
    await db_session.flush()

    incoming = await repo.list_incoming_likes(me)
    from_ids = {like.from_user_id for like in incoming}
    assert from_ids == {fresh}


@pytest.mark.asyncio
async def test_delete_user_social_data_wipes_only_my_rows(db_session) -> None:
    me = await _make_user(db_session, 20100)
    other = await _make_user(db_session, 20101)
    third = await _make_user(db_session, 20102)
    fourth = await _make_user(db_session, 20103)
    repo = MatchingRepository(db_session)

    # Активность с участием me.
    await repo.add_like(me, other, kind="like")
    await repo.add_like(third, me, kind="like")
    await repo.add_dislike(me, other)
    await repo.create_match(me, third)
    await repo.add_block(me, other)
    await repo.add_viewed(me, third)
    await repo.add_viewed(other, me)

    # Чужая активность без me.
    await repo.add_like(third, fourth, kind="like")
    await repo.add_dislike(third, fourth)
    await repo.create_match(third, fourth)
    await repo.add_block(third, fourth)
    await repo.add_viewed(third, fourth)
    await db_session.flush()

    await repo.delete_user_social_data(me)
    await db_session.flush()

    # Все строки, где me участник, удалены.
    my_likes = (
        await db_session.execute(
            select(Like).where((Like.from_user_id == me) | (Like.to_user_id == me))
        )
    ).all()
    my_dislikes = (
        await db_session.execute(
            select(Dislike).where((Dislike.from_user_id == me) | (Dislike.to_user_id == me))
        )
    ).all()
    my_matches = (
        await db_session.execute(
            select(Match).where((Match.user_a_id == me) | (Match.user_b_id == me))
        )
    ).all()
    my_blocks = (
        await db_session.execute(
            select(Block).where((Block.blocker_user_id == me) | (Block.blocked_user_id == me))
        )
    ).all()
    my_viewed = (
        await db_session.execute(
            select(ViewedProfile).where(
                (ViewedProfile.viewer_user_id == me) | (ViewedProfile.target_user_id == me)
            )
        )
    ).all()
    assert my_likes == []
    assert my_dislikes == []
    assert my_matches == []
    assert my_blocks == []
    assert my_viewed == []

    # Чужие строки остались.
    foreign_likes = (
        await db_session.execute(
            select(Like).where(Like.from_user_id == third, Like.to_user_id == fourth)
        )
    ).all()
    assert len(foreign_likes) == 1


@pytest.mark.asyncio
async def test_block_cascade_on_user_delete(db_session) -> None:
    """Удаление пользователя каскадно убирает связанные Like/Dislike/Block/Viewed."""
    a = await _make_user(db_session, 20060)
    b = await _make_user(db_session, 20061)
    repo = MatchingRepository(db_session)

    await repo.add_like(a, b, kind="like")
    await repo.add_dislike(a, b)  # этого не получится: UNIQUE по (a,b) другой таблицы, ok.
    await repo.add_block(a, b)
    await repo.add_viewed(a, b)
    await db_session.flush()

    await UserRepository(db_session).hard_delete(b)
    await db_session.flush()

    likes = (await db_session.execute(select(Like).where(Like.to_user_id == b))).all()
    dislikes = (await db_session.execute(select(Dislike).where(Dislike.to_user_id == b))).all()
    blocks = (await db_session.execute(select(Block).where(Block.blocked_user_id == b))).all()
    viewed = (
        await db_session.execute(select(ViewedProfile).where(ViewedProfile.target_user_id == b))
    ).all()
    assert likes == []
    assert dislikes == []
    assert blocks == []
    assert viewed == []
