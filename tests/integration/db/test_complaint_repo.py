from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.dictionaries import ComplaintReason
from app.db.models.moderation import Complaint
from app.db.repositories.complaint_repo import ComplaintRepository
from app.db.repositories.user_repo import UserRepository


async def _make_user(db_session, telegram_id: int) -> int:
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    return user.id


async def _spam_reason_id(db_session) -> int:
    row = (
        await db_session.execute(select(ComplaintReason).where(ComplaintReason.code == "spam"))
    ).scalar_one()
    return row.id


@pytest.mark.asyncio
async def test_create_and_get_by_id_roundtrip(db_session) -> None:
    a = await _make_user(db_session, 30001)
    b = await _make_user(db_session, 30002)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    complaint = await repo.create(a, b, reason, comment="bot spam")
    assert complaint.id is not None
    assert complaint.status == "new"

    fetched = await repo.get_by_id(complaint.id)
    assert fetched is not None
    assert fetched.from_user_id == a
    assert fetched.target_user_id == b
    assert fetched.reason_id == reason
    assert fetched.comment == "bot spam"


@pytest.mark.asyncio
async def test_count_against_user(db_session) -> None:
    target = await _make_user(db_session, 30010)
    a = await _make_user(db_session, 30011)
    b = await _make_user(db_session, 30012)
    c = await _make_user(db_session, 30013)
    other = await _make_user(db_session, 30014)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    await repo.create(a, target, reason)
    await repo.create(b, target, reason)
    await repo.create(c, target, reason)
    await repo.create(a, other, reason)

    assert await repo.count_against_user(target) == 3
    assert await repo.count_against_user(other) == 1


@pytest.mark.asyncio
async def test_resolve_sets_status_and_note(db_session) -> None:
    a = await _make_user(db_session, 30020)
    b = await _make_user(db_session, 30021)
    moderator = await _make_user(db_session, 30022)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    complaint = await repo.create(a, b, reason)
    await repo.resolve(complaint.id, moderator, note="banned target")

    fetched = await repo.get_by_id(complaint.id)
    assert fetched is not None
    await db_session.refresh(fetched)
    assert fetched is not None
    assert fetched.status == "resolved"
    assert fetched.resolved_at is not None
    assert fetched.moderator_user_id == moderator
    assert fetched.moderator_note == "banned target"


@pytest.mark.asyncio
async def test_reject_sets_status(db_session) -> None:
    a = await _make_user(db_session, 30030)
    b = await _make_user(db_session, 30031)
    moderator = await _make_user(db_session, 30032)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    complaint = await repo.create(a, b, reason)
    await repo.reject(complaint.id, moderator, note="no violation")

    fetched = await repo.get_by_id(complaint.id)
    assert fetched is not None
    await db_session.refresh(fetched)
    assert fetched is not None
    assert fetched.status == "rejected"
    assert fetched.resolved_at is not None
    assert fetched.moderator_note == "no violation"


@pytest.mark.asyncio
async def test_set_in_progress(db_session) -> None:
    a = await _make_user(db_session, 30040)
    b = await _make_user(db_session, 30041)
    moderator = await _make_user(db_session, 30042)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    complaint = await repo.create(a, b, reason)
    await repo.set_in_progress(complaint.id, moderator)
    fetched = await repo.get_by_id(complaint.id)
    assert fetched is not None
    await db_session.refresh(fetched)
    assert fetched is not None
    assert fetched.status == "in_progress"
    assert fetched.moderator_user_id == moderator


@pytest.mark.asyncio
async def test_list_by_status(db_session) -> None:
    a = await _make_user(db_session, 30050)
    b = await _make_user(db_session, 30051)
    c = await _make_user(db_session, 30052)
    moderator = await _make_user(db_session, 30053)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    c1 = await repo.create(a, b, reason)
    c2 = await repo.create(a, c, reason)
    await repo.resolve(c2.id, moderator)

    new = await repo.list_by_status("new", limit=10)
    resolved = await repo.list_by_status("resolved", limit=10)
    assert {x.id for x in new} == {c1.id}
    assert {x.id for x in resolved} == {c2.id}


@pytest.mark.asyncio
async def test_delete_by_user_removes_all_from_and_target(db_session) -> None:
    a = await _make_user(db_session, 30100)
    b = await _make_user(db_session, 30101)
    c = await _make_user(db_session, 30102)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    # Жалобы где a — автор.
    await repo.create(a, b, reason)
    # Жалобы где a — цель.
    await repo.create(b, a, reason)
    await repo.create(c, a, reason)
    # Жалобы без участия a.
    untouched = await repo.create(b, c, reason)

    await repo.delete_by_user(a)
    await db_session.flush()

    remaining = (
        await db_session.execute(
            select(Complaint).where((Complaint.from_user_id == a) | (Complaint.target_user_id == a))
        )
    ).all()
    assert remaining == []

    # Чужая жалоба не тронута.
    still_there = await repo.get_by_id(untouched.id)
    assert still_there is not None


@pytest.mark.asyncio
async def test_self_complaint_violates_check(db_session) -> None:
    a = await _make_user(db_session, 30060)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)
    with pytest.raises(IntegrityError):
        await repo.create(a, a, reason)


@pytest.mark.asyncio
async def test_list_with_details_returns_violator_and_reporter(db_session) -> None:
    """list_with_details отдаёт жалобу вместе с нарушителем и репортером."""
    reporter = await _make_user(db_session, 30200)
    violator = await _make_user(db_session, 30201)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    created = await repo.create(reporter, violator, reason, comment="спам")

    details = await repo.list_with_details(status="new")
    assert len(details) == 1
    detail = details[0]
    assert detail.complaint.id == created.id
    assert detail.violator.id == violator
    assert detail.reporter.id == reporter
    # У нарушителя нет анкеты — поле None, жалоба всё равно в выдаче.
    assert detail.violator_profile is None


@pytest.mark.asyncio
async def test_list_with_details_ordered_by_created_at(db_session) -> None:
    """Жалобы упорядочены по (created_at ASC, id ASC) — модератор идёт «вперёд»."""
    reporter = await _make_user(db_session, 30210)
    v1 = await _make_user(db_session, 30211)
    v2 = await _make_user(db_session, 30212)
    v3 = await _make_user(db_session, 30213)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    c1 = await repo.create(reporter, v1, reason)
    c2 = await repo.create(reporter, v2, reason)
    c3 = await repo.create(reporter, v3, reason)

    details = await repo.list_with_details(status="new")
    assert [d.complaint.id for d in details] == [c1.id, c2.id, c3.id]

    # offset/limit работают по тому же набору.
    page = await repo.list_with_details(status="new", offset=1, limit=1)
    assert [d.complaint.id for d in page] == [c2.id]


@pytest.mark.asyncio
async def test_count_with_details_matches_list_length(db_session) -> None:
    """count_with_details согласован с list_with_details — total не врёт."""
    reporter = await _make_user(db_session, 30220)
    v1 = await _make_user(db_session, 30221)
    v2 = await _make_user(db_session, 30222)
    moderator = await _make_user(db_session, 30223)
    reason = await _spam_reason_id(db_session)
    repo = ComplaintRepository(db_session)

    await repo.create(reporter, v1, reason)
    c2 = await repo.create(reporter, v2, reason)
    await repo.resolve(c2.id, moderator)

    new_count = await repo.count_with_details("new")
    new_list = await repo.list_with_details(status="new", limit=100)
    assert new_count == len(new_list) == 1

    resolved_count = await repo.count_with_details("resolved")
    resolved_list = await repo.list_with_details(status="resolved", limit=100)
    assert resolved_count == len(resolved_list) == 1
