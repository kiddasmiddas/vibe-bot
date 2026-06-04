"""Тесты на FeedRepository.list_comments_cursor.

После переключения порядка комментариев на ASC (старые сверху, новые внизу):
- первая страница содержит самые СТАРЫЕ комментарии;
- курсор указывает на последний (самый НОВЫЙ из показанных) комментарий;
- запрос со курсором возвращает следующих по хронологии (даже более новых).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.feed import FeedComment
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.user_repo import UserRepository


async def _make_user(db: AsyncSession, telegram_id: int) -> Any:
    repo = UserRepository(db)
    return await repo.create(telegram_id=telegram_id, username=f"u{telegram_id}")


async def _make_post(db: AsyncSession, author_user_id: int) -> Any:
    now = datetime.now(tz=UTC)
    repo = FeedRepository(db)
    return await repo.create_post(
        author_user_id=author_user_id,
        author_name="TestAuthor",
        text="Post body",
        status="active",
        is_pending_review=False,
        published_at=now,
        expires_at=now + timedelta(hours=48),
    )


async def _make_comment(
    db: AsyncSession,
    *,
    post_id: int,
    author_user_id: int,
    text: str,
    created_at: datetime,
    status: str = "active",
) -> FeedComment:
    """Создаёт комментарий и принудительно проставляет created_at.

    server_default=func.now() оставит метку времени, но для теста порядка
    нам важна явно заданная хронология — поэтому правим поле после flush.
    """
    repo = FeedRepository(db)
    comment = await repo.create_comment(
        post_id=post_id,
        author_user_id=author_user_id,
        text=text,
        status=status,
    )
    comment.created_at = created_at
    await db.flush()
    return comment


@pytest.mark.asyncio
async def test_list_comments_cursor_asc_order(db_session: AsyncSession) -> None:
    """Без курсора — комментарии возвращаются в ASC по created_at (старые первыми)."""
    user = await _make_user(db_session, telegram_id=20_001)
    post = await _make_post(db_session, user.id)
    base = datetime.now(tz=UTC) - timedelta(hours=1)

    # Создаём три комментария в произвольном порядке вставки.
    c_mid = await _make_comment(
        db_session,
        post_id=post.id,
        author_user_id=user.id,
        text="middle",
        created_at=base + timedelta(minutes=10),
    )
    c_old = await _make_comment(
        db_session,
        post_id=post.id,
        author_user_id=user.id,
        text="oldest",
        created_at=base,
    )
    c_new = await _make_comment(
        db_session,
        post_id=post.id,
        author_user_id=user.id,
        text="newest",
        created_at=base + timedelta(minutes=20),
    )

    repo = FeedRepository(db_session)
    items, next_cursor = await repo.list_comments_cursor(post_id=post.id, cursor=None, limit=10)

    assert [c.id for c in items] == [c_old.id, c_mid.id, c_new.id]
    # Лимит не достигнут — курсора нет.
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_comments_cursor_pagination_forward(db_session: AsyncSession) -> None:
    """Курсор указывает на последний (новейший) комментарий страницы; следующая
    страница возвращает комментарии хронологически ПОЗЖЕ курсора."""
    user = await _make_user(db_session, telegram_id=20_002)
    post = await _make_post(db_session, user.id)
    base = datetime.now(tz=UTC) - timedelta(hours=2)

    comments = []
    for idx in range(5):
        comments.append(
            await _make_comment(
                db_session,
                post_id=post.id,
                author_user_id=user.id,
                text=f"c{idx}",
                created_at=base + timedelta(minutes=idx),
            )
        )

    repo = FeedRepository(db_session)

    # Первая страница (limit=2) → c0, c1 (самые старые).
    page1, cursor1 = await repo.list_comments_cursor(post_id=post.id, cursor=None, limit=2)
    assert [c.id for c in page1] == [comments[0].id, comments[1].id]
    assert cursor1 is not None
    assert cursor1[1] == comments[1].id  # курсор — на последнем (новейшем) page1

    # Вторая страница: c2, c3.
    page2, cursor2 = await repo.list_comments_cursor(post_id=post.id, cursor=cursor1, limit=2)
    assert [c.id for c in page2] == [comments[2].id, comments[3].id]
    assert cursor2 is not None

    # Третья (последняя) страница: c4, курсор None.
    page3, cursor3 = await repo.list_comments_cursor(post_id=post.id, cursor=cursor2, limit=2)
    assert [c.id for c in page3] == [comments[4].id]
    assert cursor3 is None


@pytest.mark.asyncio
async def test_list_comments_cursor_same_timestamp_ties_break_by_id(
    db_session: AsyncSession,
) -> None:
    """При одинаковом created_at вторичная сортировка — по id ASC.

    Курсорное условие тоже должно различать сравнение по id для пар (ts, id).
    """
    user = await _make_user(db_session, telegram_id=20_003)
    post = await _make_post(db_session, user.id)
    ts = datetime.now(tz=UTC) - timedelta(minutes=30)

    a = await _make_comment(
        db_session,
        post_id=post.id,
        author_user_id=user.id,
        text="a",
        created_at=ts,
    )
    b = await _make_comment(
        db_session,
        post_id=post.id,
        author_user_id=user.id,
        text="b",
        created_at=ts,
    )
    c = await _make_comment(
        db_session,
        post_id=post.id,
        author_user_id=user.id,
        text="c",
        created_at=ts,
    )

    repo = FeedRepository(db_session)
    page1, cursor1 = await repo.list_comments_cursor(post_id=post.id, cursor=None, limit=2)
    assert [x.id for x in page1] == [a.id, b.id]
    assert cursor1 == (ts, b.id)

    page2, cursor2 = await repo.list_comments_cursor(post_id=post.id, cursor=cursor1, limit=2)
    assert [x.id for x in page2] == [c.id]
    assert cursor2 is None


@pytest.mark.asyncio
async def test_list_comments_cursor_excludes_non_active(db_session: AsyncSession) -> None:
    """Комментарии со статусом, отличным от active, в выдачу не попадают."""
    user = await _make_user(db_session, telegram_id=20_004)
    post = await _make_post(db_session, user.id)
    base = datetime.now(tz=UTC) - timedelta(hours=1)

    active_old = await _make_comment(
        db_session,
        post_id=post.id,
        author_user_id=user.id,
        text="active old",
        created_at=base,
    )
    await _make_comment(
        db_session,
        post_id=post.id,
        author_user_id=user.id,
        text="deleted",
        created_at=base + timedelta(minutes=5),
        status="deleted_by_user",
    )
    active_new = await _make_comment(
        db_session,
        post_id=post.id,
        author_user_id=user.id,
        text="active new",
        created_at=base + timedelta(minutes=10),
    )

    repo = FeedRepository(db_session)
    items, _ = await repo.list_comments_cursor(post_id=post.id, cursor=None, limit=10)
    assert [c.id for c in items] == [active_old.id, active_new.id]
