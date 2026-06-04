from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, desc, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.feed import (
    FeedComment,
    FeedCommentRestriction,
    FeedPost,
    FeedPostMedia,
    FeedReaction,
)


class FeedRepository:
    """Доступ к feed_posts, feed_post_media, feed_comments, feed_reactions,
    feed_comment_restrictions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    async def get_by_id(self, post_id: int) -> FeedPost | None:
        return await self._session.get(FeedPost, post_id)

    async def create_post(self, **fields: Any) -> FeedPost:
        post = FeedPost(**fields)
        self._session.add(post)
        await self._session.flush()
        return post

    async def set_post_status(self, post_id: int, status: str) -> None:
        """Сменить статус поста.

        Допустимые значения: active / expired / hidden_by_moderator / deleted_by_user / blocked.
        """
        stmt = update(FeedPost).where(FeedPost.id == post_id).values(status=status)
        await self._session.execute(stmt)
        await self._session.flush()

    async def update_post(
        self,
        post_id: int,
        *,
        text: str | None = None,
        set_pending_review: bool = False,
        updated_at: datetime | None = None,
    ) -> FeedPost | None:
        """Частичное обновление поста (Волна 3 — редактирование автором).

        Обновляются только переданные не-None поля. Если `set_pending_review=True`,
        флаг is_pending_review выставляется в True. Поле updated_at пишется явно
        (без onupdate=), чтобы случайные UPDATE на других полях не сдвигали отметку.

        Возвращает обновлённый объект FeedPost или None, если поста нет.
        Не меняет expires_at — 48-часовой таймер по ТЗ продолжает идти от created_at.
        """
        values: dict[str, Any] = {}
        if text is not None:
            values["text"] = text
        if set_pending_review:
            values["is_pending_review"] = True
        if updated_at is not None:
            values["updated_at"] = updated_at

        if not values:
            return await self._session.get(FeedPost, post_id)

        stmt = update(FeedPost).where(FeedPost.id == post_id).values(**values).returning(FeedPost)
        result = await self._session.execute(stmt)
        post = result.scalar_one_or_none()
        await self._session.flush()
        return post

    async def replace_media(
        self,
        post_id: int,
        new_media: list[dict[str, Any]],
    ) -> list[FeedPostMedia]:
        """Атомарно заменить весь набор медиа у поста.

        Удаляет все существующие FeedPostMedia для поста и вставляет новые
        в указанном порядке. Элементы `new_media` — dict с ключами:
        - `file_id: str`
        - `media_type: str` (например, "photo" или "gif")
        - `sort_order: int` (позиция в карусели)

        Один транзакционный блок (flush в конце) — вызывающий коммитит сам.
        Возвращает созданные объекты FeedPostMedia в порядке вставки.
        """
        delete_stmt = delete(FeedPostMedia).where(FeedPostMedia.post_id == post_id)
        await self._session.execute(delete_stmt)

        created: list[FeedPostMedia] = []
        for item in new_media:
            media = FeedPostMedia(
                post_id=post_id,
                media_type=item["media_type"],
                file_id=item["file_id"],
                position=item["sort_order"],
            )
            self._session.add(media)
            created.append(media)

        await self._session.flush()
        return created

    async def count_posts_by_user_since(self, user_id: int, since: datetime) -> int:
        """Число постов пользователя, созданных начиная с `since`.

        Используется для месячного лимита Premium-пользователей.
        """
        stmt = select(func.count()).where(
            FeedPost.author_user_id == user_id,
            FeedPost.created_at >= since,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def add_photo(self, post_id: int, file_id: str, position: int) -> FeedPostMedia:
        media = FeedPostMedia(
            post_id=post_id,
            media_type="photo",
            file_id=file_id,
            position=position,
        )
        self._session.add(media)
        await self._session.flush()
        return media

    async def list_active_cursor(
        self,
        cursor: tuple[datetime, int] | None,
        limit: int,
    ) -> tuple[list[FeedPost], tuple[datetime, int] | None]:
        """Активные, не истёкшие посты с курсорной пагинацией.

        ORDER BY published_at DESC, id DESC. Курсор — пара (published_at, id)
        последнего возвращённого поста.

        Возвращает `(posts, next_cursor)`, где `next_cursor is None` — конец ленты.
        """
        now = datetime.now(tz=UTC)
        base_filter = and_(
            FeedPost.status == "active",
            FeedPost.expires_at > now,
            FeedPost.published_at.is_not(None),
            # Посты на премодерации не показываем в публичной ленте (ТЗ п.2).
            FeedPost.is_pending_review.is_(False),
        )

        if cursor is not None:
            cursor_ts, cursor_id = cursor
            cursor_filter = or_(
                FeedPost.published_at < cursor_ts,
                and_(
                    FeedPost.published_at == cursor_ts,
                    FeedPost.id < cursor_id,
                ),
            )
            stmt = (
                select(FeedPost)
                .where(base_filter, cursor_filter)
                .order_by(desc(FeedPost.published_at), desc(FeedPost.id))
                .limit(limit)
            )
        else:
            stmt = (
                select(FeedPost)
                .where(base_filter)
                .order_by(desc(FeedPost.published_at), desc(FeedPost.id))
                .limit(limit)
            )

        posts = list((await self._session.execute(stmt)).scalars().all())
        next_cursor: tuple[datetime, int] | None = None
        if len(posts) == limit:
            last = posts[-1]
            assert last.published_at is not None
            next_cursor = (last.published_at, last.id)
        return posts, next_cursor

    async def get_photos_for_post(self, post_id: int) -> list[FeedPostMedia]:
        """Медиафайлы поста, отсортированные по position."""
        stmt = (
            select(FeedPostMedia)
            .where(FeedPostMedia.post_id == post_id)
            .order_by(FeedPostMedia.position)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_photos_for_posts(self, post_ids: list[int]) -> dict[int, list[FeedPostMedia]]:
        """Медиафайлы для нескольких постов одним запросом.

        Возвращает dict post_id -> list[FeedPostMedia].
        """
        if not post_ids:
            return {}
        stmt = (
            select(FeedPostMedia)
            .where(FeedPostMedia.post_id.in_(post_ids))
            .order_by(FeedPostMedia.post_id, FeedPostMedia.position)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        result: dict[int, list[FeedPostMedia]] = {pid: [] for pid in post_ids}
        for media in rows:
            result[media.post_id].append(media)
        return result

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    async def create_comment(self, **fields: Any) -> FeedComment:
        """Создать комментарий. Должен содержать либо text, либо media_type + media_file_id."""
        comment = FeedComment(**fields)
        self._session.add(comment)
        await self._session.flush()
        return comment

    async def get_comment(self, comment_id: int) -> FeedComment | None:
        return await self._session.get(FeedComment, comment_id)

    async def list_comments_cursor(
        self,
        post_id: int,
        cursor: tuple[datetime, int] | None,
        limit: int,
    ) -> tuple[list[FeedComment], tuple[datetime, int] | None]:
        """Активные комментарии поста с курсорной пагинацией.

        ORDER BY created_at ASC, id ASC — старые комментарии первыми, новые внизу
        (как в чатах). Возвращает только status='active'.

        Курсор кодирует (created_at, id) последнего возвращённого комментария.
        Следующая страница — это комментарии, которые ХРОНОЛОГИЧЕСКИ ПОЗЖЕ курсора:
        `created_at > cursor_ts` или `(created_at == cursor_ts AND id > cursor_id)`.
        """
        base_filter = and_(
            FeedComment.post_id == post_id,
            FeedComment.status == "active",
        )

        if cursor is not None:
            cursor_ts, cursor_id = cursor
            cursor_filter = or_(
                FeedComment.created_at > cursor_ts,
                and_(
                    FeedComment.created_at == cursor_ts,
                    FeedComment.id > cursor_id,
                ),
            )
            stmt = (
                select(FeedComment)
                .where(base_filter, cursor_filter)
                .order_by(FeedComment.created_at, FeedComment.id)
                .limit(limit)
            )
        else:
            stmt = (
                select(FeedComment)
                .where(base_filter)
                .order_by(FeedComment.created_at, FeedComment.id)
                .limit(limit)
            )

        comments = list((await self._session.execute(stmt)).scalars().all())
        next_cursor: tuple[datetime, int] | None = None
        if len(comments) == limit:
            last = comments[-1]
            next_cursor = (last.created_at, last.id)
        return comments, next_cursor

    async def set_comment_status(self, comment_id: int, status: str) -> None:
        """Сменить статус комментария (active / deleted_by_user / deleted_by_moderator)."""
        stmt = update(FeedComment).where(FeedComment.id == comment_id).values(status=status)
        await self._session.execute(stmt)
        await self._session.flush()

    async def count_comments_by_user_since(self, user_id: int, since: datetime) -> int:
        """Число комментариев пользователя, созданных начиная с `since`. Для дневного лимита."""
        # Удалённые комментарии не должны расходовать дневной лимит.
        stmt = select(func.count()).where(
            FeedComment.author_user_id == user_id,
            FeedComment.created_at >= since,
            FeedComment.status == "active",
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    async def set_reaction(self, post_id: int, user_id: int, reaction_type: str) -> FeedReaction:
        """UPSERT реакции: вставить или заменить reaction_type для пары (post_id, user_id)."""
        stmt = (
            pg_insert(FeedReaction)
            .values(post_id=post_id, user_id=user_id, reaction_type=reaction_type)
            .on_conflict_do_update(
                index_elements=["post_id", "user_id"],
                set_={"reaction_type": reaction_type},
            )
            .returning(FeedReaction)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def remove_reaction(self, post_id: int, user_id: int) -> None:
        """Удалить реакцию пользователя с поста."""
        stmt = delete(FeedReaction).where(
            FeedReaction.post_id == post_id,
            FeedReaction.user_id == user_id,
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def get_user_reaction(self, post_id: int, user_id: int) -> FeedReaction | None:
        stmt = select(FeedReaction).where(
            FeedReaction.post_id == post_id,
            FeedReaction.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_reactions_by_post(self, post_id: int) -> dict[str, int]:
        """Счётчики реакций по типам для поста. Возвращает dict reaction_type -> count."""
        stmt = (
            select(FeedReaction.reaction_type, func.count().label("cnt"))
            .where(FeedReaction.post_id == post_id)
            .group_by(FeedReaction.reaction_type)
        )
        rows = (await self._session.execute(stmt)).all()
        return {row.reaction_type: row.cnt for row in rows}

    # ------------------------------------------------------------------
    # Comment restrictions
    # ------------------------------------------------------------------

    async def get_active_restriction(
        self, user_id: int, now: datetime
    ) -> FeedCommentRestriction | None:
        """Вернуть активное ограничение пользователя, если until > now."""
        stmt = select(FeedCommentRestriction).where(
            FeedCommentRestriction.user_id == user_id,
            FeedCommentRestriction.until > now,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_restriction(
        self, user_id: int, until: datetime, admin_id: int | None
    ) -> FeedCommentRestriction:
        """Установить или заменить ограничение пользователя в комментариях."""
        stmt = (
            pg_insert(FeedCommentRestriction)
            .values(user_id=user_id, until=until, created_by_admin_id=admin_id)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={"until": until, "created_by_admin_id": admin_id},
            )
            .returning(FeedCommentRestriction)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def remove_restriction(self, user_id: int) -> None:
        """Снять ограничение пользователя в комментариях."""
        stmt = delete(FeedCommentRestriction).where(FeedCommentRestriction.user_id == user_id)
        await self._session.execute(stmt)
        await self._session.flush()

    # ------------------------------------------------------------------
    # Scheduler helpers (Волна 2B)
    # ------------------------------------------------------------------

    async def expire_active_posts(self, now: datetime) -> int:
        """Перевести просроченные активные посты в статус 'expired'.

        UPDATE feed_posts SET status='expired'
        WHERE status='active' AND expires_at < now.
        Возвращает количество обновлённых строк.
        """
        stmt = (
            update(FeedPost)
            .where(
                FeedPost.status == "active",
                FeedPost.expires_at < now,
            )
            .values(status="expired")
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount  # type: ignore[return-value]

    async def purge_old_posts(self, before: datetime) -> int:
        """Физически удалить посты, удовлетворяющие условию purge.

        DELETE FROM feed_posts
        WHERE status IN ('expired','hidden_by_moderator','deleted_by_user','blocked')
        AND expires_at < before.
        CASCADE удалит связанные media/comments/reactions.
        Возвращает количество удалённых строк.
        """
        stmt = delete(FeedPost).where(
            FeedPost.status.in_(["expired", "hidden_by_moderator", "deleted_by_user", "blocked"]),
            FeedPost.expires_at < before,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Admin moderation helpers (Волна 2B)
    # ------------------------------------------------------------------

    async def approve_post(self, post_id: int) -> None:
        """Снять флаг is_pending_review с поста (одобрить премодерацию)."""
        stmt = update(FeedPost).where(FeedPost.id == post_id).values(is_pending_review=False)
        await self._session.execute(stmt)
        await self._session.flush()

    async def count_pending_review_posts(self) -> int:
        """Число постов, ожидающих ручной проверки (is_pending_review=True, status='active')."""
        stmt = select(func.count()).where(
            FeedPost.is_pending_review.is_(True),
            FeedPost.status == "active",
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_posts_by_status(self, status: str) -> int:
        """Число постов с заданным статусом."""
        stmt = select(func.count()).where(FeedPost.status == status)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def list_pending_review_posts(self, limit: int = 20, offset: int = 0) -> list[FeedPost]:
        """Список постов, ожидающих ручной проверки (is_pending_review=True).

        Сортировка: created_at ASC (старые — первыми, чтобы обрабатывать в очереди).
        """
        stmt = (
            select(FeedPost)
            .where(
                FeedPost.is_pending_review.is_(True),
                FeedPost.status == "active",
            )
            .order_by(FeedPost.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_posts_by_status(
        self, status: str, limit: int = 20, offset: int = 0
    ) -> list[FeedPost]:
        """Список постов по статусу. Используется в админской панели Ленты."""
        stmt = (
            select(FeedPost)
            .where(FeedPost.status == status)
            .order_by(desc(FeedPost.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())
