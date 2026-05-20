from __future__ import annotations

import pytest

from app.db.repositories.promo_repo import PromoRepository
from app.db.repositories.user_repo import UserRepository


async def _make_user(db_session, telegram_id: int) -> int:
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    return user.id


@pytest.mark.asyncio
async def test_create_draft_and_update(db_session) -> None:
    repo = PromoRepository(db_session)
    post = await repo.create_draft(
        text="Hello",
        target_segment="all",
    )
    assert post.id is not None
    assert post.status == "draft"
    assert post.target_segment == "all"
    assert post.total_recipients == 0

    updated = await repo.update(post.id, title="Greeting", status="queued")
    assert updated.title == "Greeting"
    assert updated.status == "queued"


@pytest.mark.asyncio
async def test_add_recipients_idempotent(db_session) -> None:
    repo = PromoRepository(db_session)
    u1 = await _make_user(db_session, 40001)
    u2 = await _make_user(db_session, 40002)
    u3 = await _make_user(db_session, 40003)

    post = await repo.create_draft(text="hi", target_segment="custom")

    await repo.add_recipients(post.id, [u1, u2])
    # Дублирующий вызов с пересечением — не должен падать (ON CONFLICT DO NOTHING).
    await repo.add_recipients(post.id, [u2, u3])

    refreshed = await repo.recount_progress(post.id)
    assert refreshed.total_recipients == 3
    assert refreshed.delivered_count == 0
    assert refreshed.failed_count == 0


@pytest.mark.asyncio
async def test_mark_sent_failed_and_recount(db_session) -> None:
    repo = PromoRepository(db_session)
    u1 = await _make_user(db_session, 40010)
    u2 = await _make_user(db_session, 40011)
    u3 = await _make_user(db_session, 40012)
    post = await repo.create_draft(text="x", target_segment="all")

    await repo.add_recipients(post.id, [u1, u2, u3])
    await repo.mark_recipient_sent(post.id, u1)
    await repo.mark_recipient_sent(post.id, u2)
    await repo.mark_recipient_failed(post.id, u3, error="blocked bot")

    refreshed = await repo.recount_progress(post.id)
    assert refreshed.total_recipients == 3
    assert refreshed.delivered_count == 2
    assert refreshed.failed_count == 1


@pytest.mark.asyncio
async def test_list_by_status(db_session) -> None:
    repo = PromoRepository(db_session)
    p1 = await repo.create_draft(text="a", target_segment="all")
    p2 = await repo.create_draft(text="b", target_segment="all", status="queued")

    drafts = await repo.list_by_status("draft", limit=10)
    queued = await repo.list_by_status("queued", limit=10)
    assert p1.id in {x.id for x in drafts}
    assert p2.id in {x.id for x in queued}
