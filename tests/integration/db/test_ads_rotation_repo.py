"""Тесты AdsRotationRepository: round-robin выбор и CRUD пула авто-рекламы."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.ads_rotation_repo import AdsRotationRepository


@pytest.mark.asyncio
async def test_pick_next_round_robin(db_session: AsyncSession) -> None:
    """pick_next выдаёт креативы по кругу: A, B, C, A, B, C…"""
    repo = AdsRotationRepository(db_session)
    a = await repo.create(text="A")
    b = await repo.create(text="B")
    c = await repo.create(text="C")

    picks = [await repo.pick_next() for _ in range(6)]
    ids = [p.id for p in picks if p is not None]

    assert ids == [a.id, b.id, c.id, a.id, b.id, c.id]
    # shown_count у каждого вырос на 2 (показан дважды за 6 итераций).
    await db_session.refresh(a)
    assert a.shown_count == 2


@pytest.mark.asyncio
async def test_pick_next_empty_pool(db_session: AsyncSession) -> None:
    repo = AdsRotationRepository(db_session)
    assert await repo.pick_next() is None


@pytest.mark.asyncio
async def test_crud(db_session: AsyncSession) -> None:
    repo = AdsRotationRepository(db_session)
    ad = await repo.create(
        text="Реклама",
        media_file_id="file_1",
        media_type="photo",
        button_label="Купить",
        button_target="premium",
        button_url=None,
    )
    assert await repo.count() == 1

    fetched = await repo.get_by_id(ad.id)
    assert fetched is not None and fetched.button_target == "premium"

    updated = await repo.update_fields(ad.id, text="Новый текст", button_label="Перейти")
    assert updated.text == "Новый текст"
    assert updated.button_label == "Перейти"

    assert await repo.delete(ad.id) is True
    assert await repo.get_by_id(ad.id) is None
    assert await repo.delete(ad.id) is False  # повторное удаление — no-op


@pytest.mark.asyncio
async def test_pick_next_prefers_never_shown(db_session: AsyncSession) -> None:
    """Новый креатив (last_shown_at IS NULL) встаёт раньше уже показанных."""
    repo = AdsRotationRepository(db_session)
    await repo.create(text="old")
    await repo.pick_next()  # old показан → last_shown_at не NULL
    fresh = await repo.create(text="fresh")  # last_shown_at NULL

    nxt = await repo.pick_next()
    assert nxt is not None and nxt.id == fresh.id  # NULLS FIRST → новый раньше
