from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.dictionaries import CreatorCategory
from app.db.repositories.creator_repo import CreatorRepository


async def _seed_category(db_session, code: str) -> CreatorCategory:
    cat = CreatorCategory(code=code, title=code.title())
    db_session.add(cat)
    await db_session.flush()
    return cat


async def _make_post(db_session, *, code: str, expires_in_days: int, is_published: bool = True):
    cat = await _seed_category(db_session, code)
    repo = CreatorRepository(db_session)
    now = datetime.now(tz=UTC)
    return await repo.create_post(
        author_display_name="Author",
        category_id=cat.id,
        description="hello",
        telegram_link="https://t.me/x",
        is_premium_post=False,
        published_at=now,
        expires_at=now + timedelta(days=expires_in_days),
        is_published=is_published,
    )


@pytest.mark.asyncio
async def test_create_post_and_add_photos(db_session) -> None:
    post = await _make_post(db_session, code="cat_one", expires_in_days=7)
    repo = CreatorRepository(db_session)

    p0 = await repo.add_photo(post.id, "file0", 0)
    p1 = await repo.add_photo(post.id, "file1", 1)
    p2 = await repo.add_photo(post.id, "file2", 2)
    assert {p0.position, p1.position, p2.position} == {0, 1, 2}


@pytest.mark.asyncio
async def test_unique_post_position_violation(db_session) -> None:
    post = await _make_post(db_session, code="cat_two", expires_in_days=7)
    repo = CreatorRepository(db_session)

    await repo.add_photo(post.id, "file0", 0)
    with pytest.raises(IntegrityError):
        await repo.add_photo(post.id, "file0_dup", 0)


@pytest.mark.asyncio
async def test_list_published_excludes_expired(db_session) -> None:
    # Один свежий пост и один «истёкший» (expires_at в прошлом).
    fresh = await _make_post(db_session, code="cat_fresh", expires_in_days=10)
    cat = await _seed_category(db_session, "cat_expired")
    repo = CreatorRepository(db_session)
    past = datetime.now(tz=UTC) - timedelta(days=1)
    expired = await repo.create_post(
        author_display_name="A",
        category_id=cat.id,
        description="old",
        telegram_link="https://t.me/y",
        is_premium_post=False,
        published_at=past - timedelta(days=10),
        expires_at=past,
        is_published=True,
    )

    items = await repo.list_published(limit=10, offset=0)
    ids = {p.id for p in items}
    assert fresh.id in ids
    assert expired.id not in ids


@pytest.mark.asyncio
async def test_list_published_excludes_pending_review(db_session) -> None:
    """: посты с is_pending_review=True не должны попадать в ленту."""
    visible = await _make_post(db_session, code="cat_visible_pr", expires_in_days=10)
    pending = await _make_post(db_session, code="cat_pending_pr", expires_in_days=10)
    pending.is_pending_review = True
    await db_session.flush()

    items = await CreatorRepository(db_session).list_published(limit=10, offset=0)
    ids = {p.id for p in items}
    assert visible.id in ids
    assert pending.id not in ids


@pytest.mark.asyncio
async def test_expire_post_removes_from_list_published(db_session) -> None:
    post = await _make_post(db_session, code="cat_exp", expires_in_days=10)
    repo = CreatorRepository(db_session)

    assert post.id in {p.id for p in await repo.list_published(limit=10)}
    await repo.expire_post(post.id)
    await db_session.refresh(post)
    assert post.is_published is False
    assert post.id not in {p.id for p in await repo.list_published(limit=10)}


@pytest.mark.asyncio
async def test_list_expiring_soon(db_session) -> None:
    soon = await _make_post(db_session, code="cat_soon", expires_in_days=2)
    later = await _make_post(db_session, code="cat_later", expires_in_days=30)
    repo = CreatorRepository(db_session)

    items = await repo.list_expiring_soon(days=5)
    ids = {p.id for p in items}
    assert soon.id in ids
    assert later.id not in ids
