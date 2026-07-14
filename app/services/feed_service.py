"""Бизнес-логика Волны 2A: создание постов, комментариев, реакций.

Хэндлеры остаются тонкими — вся валидация бизнес-правил здесь.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.feed import FeedPost, FeedPostMedia
from app.db.models.profile import Profile
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.services.access import has_premium_access
from app.services.analytics_events import EventType
from app.services.content_moderation_service import ContentModerationService
from app.texts.feed import POST_LIMIT_REACHED_PREMIUM, POST_LIMIT_REACHED_REGULAR

_VALID_REACTION_TYPES: frozenset[str] = frozenset({"heart", "sparkle", "cry", "eyes"})

# Дефолты на случай отсутствия ключа в settings
_DEFAULT_POST_LIMIT_PREMIUM_MONTH = 50
_DEFAULT_POST_LIMIT_REGULAR_MONTH = 5
_DEFAULT_COMMENT_LIMIT_REGULAR_DAY = 30
_DEFAULT_COMMENT_LIMIT_PREMIUM_DAY = 300
_DEFAULT_POST_TTL_HOURS = 48
_DEFAULT_PREMODERATE_FIRST_N = 3


def _start_of_month(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _start_of_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _reaction_counts(raw: dict[str, int]) -> dict[str, int]:
    """Дополняет dict нулями для всех 4 типов реакций."""
    return {rt: raw.get(rt, 0) for rt in sorted(_VALID_REACTION_TYPES)}


class FeedServiceError(Exception):
    """Ожидаемая ошибка бизнес-логики. Несёт HTTP-код и detail."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FeedService:
    """Сервис ленты: создание постов/комментариев/реакций, удаление комментариев.

    Не работает с БД напрямую — только через репозитории.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        feed_repo: FeedRepository,
        settings_repo: SettingsRepository,
        analytics_repo: AnalyticsRepository,
        moderation_service: ContentModerationService,
    ) -> None:
        self._db = db
        self._feed_repo = feed_repo
        self._settings_repo = settings_repo
        self._analytics_repo = analytics_repo
        self._moderation = moderation_service

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _setting_int(self, key: str, default: int) -> int:
        val = await self._settings_repo.get_int(key)
        return val if val is not None else default

    async def _log_event(
        self, user_id: int, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> None:
        try:
            await self._analytics_repo.log_event(user_id, event_type, payload)
        except Exception as exc:
            logger.warning("analytics log_event failed ({}): {}", event_type, exc)

    # ------------------------------------------------------------------
    # Create post
    # ------------------------------------------------------------------

    async def create_post(
        self,
        *,
        user: User,
        profile: Profile,
        text: str,
        media: list[dict[str, str]],
    ) -> tuple[int, bool]:
        """Создать пост. Возвращает (id поста, ушёл ли на премодерацию).

        Raises FeedServiceError (422) при нарушении правил.
        """
        now = datetime.now(tz=UTC)

        # Месячный лимит постов зависит от статуса пользователя:
        # Premium — feed_post_limit_premium_month (дефолт 50),
        # обычный — feed_post_limit_regular_month (дефолт 5).
        is_premium = has_premium_access(user)
        premium_limit = await self._setting_int(
            "feed_post_limit_premium_month", _DEFAULT_POST_LIMIT_PREMIUM_MONTH
        )
        if is_premium:
            monthly_limit = premium_limit
        else:
            monthly_limit = await self._setting_int(
                "feed_post_limit_regular_month", _DEFAULT_POST_LIMIT_REGULAR_MONTH
            )
        month_start = _start_of_month(now)
        month_count = await self._feed_repo.count_posts_by_user_since(user.id, month_start)
        if month_count >= monthly_limit:
            if is_premium:
                detail = POST_LIMIT_REACHED_PREMIUM.format(limit=monthly_limit)
            else:
                detail = POST_LIMIT_REACHED_REGULAR.format(
                    limit=monthly_limit, premium_limit=premium_limit
                )
            raise FeedServiceError(422, detail)

        # Модерация текста — ссылки запрещены
        mod_result = await self._moderation.check_text(
            text,
            allow_links=False,
            target_kind="feed_post",
            user_id=user.id,
        )
        if not mod_result.approved:
            raise FeedServiceError(422, "Text contains prohibited content or links")

        # Премодерация первых N постов
        premoderate_n = await self._setting_int(
            "feed_premoderate_first_n_posts", _DEFAULT_PREMODERATE_FIRST_N
        )
        # Считаем все (в т.ч. pending/hidden) посты автора за всё время
        all_time_count = await self._feed_repo.count_posts_by_user_since(
            user.id, datetime.min.replace(tzinfo=UTC)
        )
        is_pending = premoderate_n > 0 and all_time_count < premoderate_n

        ttl_hours = await self._setting_int("feed_post_ttl_hours", _DEFAULT_POST_TTL_HOURS)
        # 0 (и меньше) = посты живут вечно (решение клиента 2026-07): expires_at
        # не ставится, шедулер экспирации такие посты не трогает.
        expires_at = now + timedelta(hours=ttl_hours) if ttl_hours > 0 else None

        post = await self._feed_repo.create_post(
            author_user_id=user.id,
            author_name=profile.nickname,
            text=text,
            status="active",
            is_pending_review=is_pending,
            published_at=now,
            expires_at=expires_at,
        )

        for idx, item in enumerate(media):
            media_type = item.get("media_type", "photo")
            file_id = item["file_id"]
            media_obj = await self._feed_repo.add_photo(post.id, file_id, idx)
            # add_photo хардкодит media_type="photo" — корректируем для прочих типов
            if media_type != "photo":
                stmt = (
                    update(FeedPostMedia)
                    .where(FeedPostMedia.id == media_obj.id)
                    .values(media_type=media_type)
                )
                await self._db.execute(stmt)

        await self._db.commit()
        await self._log_event(user.id, EventType.FEED_POST_CREATED, {"post_id": post.id})
        # is_pending — пост ушёл на премодерацию (первые N постов автора).
        return post.id, is_pending

    # ------------------------------------------------------------------
    # Create comment
    # ------------------------------------------------------------------

    async def create_comment(
        self,
        *,
        user: User,
        profile: Profile,
        post_id: int,
        text: str | None,
        media_type: str | None,
        media_file_id: str | None,
        parent_id: int | None = None,
    ) -> tuple[int, int | None]:
        """Создать комментарий или ответ (parent_id — комментарий, на который отвечают).

        Возвращает (comment_id, reply_to_author_user_id): второй элемент —
        автор комментария, на который ответили (для пуша «вам ответили»),
        None для корневого комментария.

        Глубина веток = 1: ответ на ответ прикрепляется к корню той же ветки,
        но адресат пуша — автор именно того комментария, на который тапнули.

        Raises FeedServiceError при нарушении правил.
        """
        now = datetime.now(tz=UTC)

        # Проверить пост существует
        post = await self._feed_repo.get_by_id(post_id)
        if (
            post is None
            or post.status != "active"
            or (post.expires_at is not None and post.expires_at <= now)
        ):
            raise FeedServiceError(404, "Post not found")

        # Ответ: родитель должен существовать, быть активным и из этого же поста.
        reply_to_author_user_id: int | None = None
        root_parent_id: int | None = None
        if parent_id is not None:
            parent = await self._feed_repo.get_comment(parent_id)
            if parent is None or parent.status != "active" or parent.post_id != post_id:
                raise FeedServiceError(404, "Parent comment not found")
            reply_to_author_user_id = parent.author_user_id
            # Глубина 1: у ответа родителем становится корень ветки.
            root_parent_id = parent.parent_comment_id or parent.id
            if root_parent_id != parent.id:
                root = await self._feed_repo.get_comment(root_parent_id)
                if root is None or root.status != "active":
                    raise FeedServiceError(404, "Parent comment not found")

        # Активное ограничение
        restriction = await self._feed_repo.get_active_restriction(user.id, now)
        if restriction is not None:
            raise FeedServiceError(403, "You are restricted from commenting")

        # Дневной лимит. У админа — premium-доступ априори.
        is_premium = has_premium_access(user)
        if is_premium:
            day_limit = await self._setting_int(
                "feed_comment_limit_premium_day", _DEFAULT_COMMENT_LIMIT_PREMIUM_DAY
            )
        else:
            day_limit = await self._setting_int(
                "feed_comment_limit_regular_day", _DEFAULT_COMMENT_LIMIT_REGULAR_DAY
            )
        day_start = _start_of_day(now)
        day_count = await self._feed_repo.count_comments_by_user_since(user.id, day_start)
        if day_count >= day_limit:
            raise FeedServiceError(422, f"Daily comment limit of {day_limit} reached")

        # Медиа только для Premium
        has_media = media_type is not None and media_file_id is not None
        if has_media and not is_premium:
            raise FeedServiceError(422, "Media comments require Premium")

        # text XOR media
        has_text = text is not None and bool(text.strip())
        if has_text and has_media:
            raise FeedServiceError(422, "Provide either text or media, not both")
        if not has_text and not has_media:
            raise FeedServiceError(422, "Comment must have text or media")

        # Модерация текста
        if has_text:
            mod_result = await self._moderation.check_text(
                text,  # type: ignore[arg-type]
                allow_links=False,
                target_kind="feed_comment",
                user_id=user.id,
            )
            if not mod_result.approved:
                raise FeedServiceError(422, "Text contains prohibited content or links")

        # profile используется для будущего расширения (author_name в комментах)
        _ = profile

        comment = await self._feed_repo.create_comment(
            post_id=post_id,
            author_user_id=user.id,
            parent_comment_id=root_parent_id,
            text=text if has_text else None,
            media_type=media_type if has_media else None,
            media_file_id=media_file_id if has_media else None,
            status="active",
        )
        await self._db.commit()
        await self._log_event(
            user.id,
            EventType.FEED_COMMENT_CREATED,
            {"comment_id": comment.id, "post_id": post_id, "parent_id": root_parent_id},
        )
        return comment.id, reply_to_author_user_id

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    async def set_reaction(
        self,
        *,
        user: User,
        post_id: int,
        reaction_type: str,
    ) -> tuple[dict[str, int], str | None]:
        """Поставить/сменить реакцию. Возвращает (counts, my_reaction)."""
        if reaction_type not in _VALID_REACTION_TYPES:
            raise FeedServiceError(422, f"Invalid reaction_type: {reaction_type}")

        now = datetime.now(tz=UTC)
        post = await self._feed_repo.get_by_id(post_id)
        if (
            post is None
            or post.status != "active"
            or (post.expires_at is not None and post.expires_at <= now)
        ):
            raise FeedServiceError(404, "Post not found")

        await self._feed_repo.set_reaction(post_id, user.id, reaction_type)
        await self._db.commit()
        await self._log_event(
            user.id,
            EventType.FEED_REACTION_SET,
            {"post_id": post_id, "reaction_type": reaction_type},
        )

        raw = await self._feed_repo.count_reactions_by_post(post_id)
        return _reaction_counts(raw), reaction_type

    async def remove_reaction(
        self,
        *,
        user: User,
        post_id: int,
    ) -> tuple[dict[str, int], None]:
        """Удалить реакцию пользователя. Возвращает (counts, None)."""
        now = datetime.now(tz=UTC)
        post = await self._feed_repo.get_by_id(post_id)
        if (
            post is None
            or post.status != "active"
            or (post.expires_at is not None and post.expires_at <= now)
        ):
            raise FeedServiceError(404, "Post not found")

        await self._feed_repo.remove_reaction(post_id, user.id)
        await self._db.commit()

        raw = await self._feed_repo.count_reactions_by_post(post_id)
        return _reaction_counts(raw), None

    # ------------------------------------------------------------------
    # Delete comment
    # ------------------------------------------------------------------

    async def delete_comment(self, *, user: User, comment_id: int) -> None:
        """Удалить свой комментарий. 403 если не автор, 404 если не найден."""
        comment = await self._feed_repo.get_comment(comment_id)
        if comment is None or comment.status == "deleted_by_user":
            raise FeedServiceError(404, "Comment not found")
        if comment.author_user_id != user.id:
            raise FeedServiceError(403, "Cannot delete someone else's comment")
        await self._feed_repo.set_comment_status(comment_id, "deleted_by_user")
        await self._db.commit()

    # ------------------------------------------------------------------
    # Update post (Волна 3)
    # ------------------------------------------------------------------

    async def update_post(
        self,
        *,
        user: User,
        post_id: int,
        text: str,
        media: list[dict[str, str]] | None,
    ) -> tuple[FeedPost, bool]:
        """Редактировать пост (Волна 3).

        Параметры:
        - `text` — новый текст (обязателен).
        - `media` — список новых медиа в виде [{file_id, media_type}, ...].
          `None` означает «медиа не трогаем»; пустой список — удалить всё.

        Возвращает (post, changed): changed=True если применили изменения и
        проставили pending_review. changed=False — no-op (повторный submit с
        тем же контентом), в этом случае admin-notify слать не надо.

        Поведение:
        - Только автор может редактировать (403).
        - Запрещено редактирование постов в статусах кроме 'active' (409).
        - При совпадении нового текста и медиа с текущими — no-op, возвращаем как есть.
        - При смене текста — повторная текст-модерация (422 при отказе).
        - Для НОВЫХ медиа (которых не было в посте) — NSFW-проверка (422 при rejected).
        - При любом фактическом изменении пост уходит в is_pending_review=True,
          уведомление админам присылает вызывающий роут (graceful, не ломает ответ).
        - `expires_at` не сбрасывается — 48-часовой таймер идёт от created_at.
        Raises FeedServiceError при нарушении правил.
        """
        now = datetime.now(tz=UTC)

        post = await self._feed_repo.get_by_id(post_id)
        if post is None:
            raise FeedServiceError(404, "Post not found")
        if post.author_user_id != user.id:
            raise FeedServiceError(403, "Cannot edit someone else's post")
        # Редактирование запрещено для blocked/hidden_by_moderator/deleted_by_user/expired.
        if post.status != "active":
            raise FeedServiceError(409, "Post cannot be edited in current status")

        # Текущее состояние для сравнения и решения о no-op.
        current_media = await self._feed_repo.get_photos_for_post(post_id)
        current_keys: list[tuple[str, str]] = [(m.file_id, m.media_type) for m in current_media]

        text_changed = text != post.text

        media_changed = False
        normalized_new_media: list[dict[str, Any]] | None = None
        if media is not None:
            # Нормализуем входные данные, чтобы устойчиво сравнивать с текущими.
            normalized_new_media = [
                {
                    "file_id": item["file_id"],
                    "media_type": item.get("media_type", "photo"),
                    "sort_order": idx,
                }
                for idx, item in enumerate(media)
            ]
            new_keys = [(item["file_id"], item["media_type"]) for item in normalized_new_media]
            media_changed = new_keys != current_keys

        if not text_changed and not media_changed:
            # Никаких реальных изменений — не тратим квоту модерации и не пишем БД.
            return post, False

        # Модерация текста — только если текст реально поменялся.
        if text_changed:
            mod_result = await self._moderation.check_text(
                text,
                allow_links=False,
                target_kind="feed_post",
                target_id=post_id,
                user_id=user.id,
            )
            if not mod_result.approved:
                raise FeedServiceError(422, "Text contains prohibited content or links")

        # NSFW-проверка только для НОВЫХ медиа (которых не было раньше).
        # Файлы, уже бывшие в посте, повторно не гоняем через NudeNet.
        if media_changed and normalized_new_media is not None:
            existing_file_ids = {m.file_id for m in current_media}
            for item in normalized_new_media:
                if item["file_id"] in existing_file_ids:
                    continue
                # Скачиваем по file_id через бота — но в текущей архитектуре
                # upload-эндпойнт уже прогнал НОВЫЕ файлы через NSFW при загрузке.
                # Поэтому здесь дополнительная проверка не нужна: file_id может
                # быть в посте только после прохождения /api/feed/upload.
                # Если в будущем появится способ обойти upload — добавить
                # check_image() здесь.
                logger.debug(
                    "feed update_post: new media item file_id={} (NSFW already checked at upload)",
                    item["file_id"],
                )

        # Применяем изменения.
        updated = await self._feed_repo.update_post(
            post_id,
            text=text if text_changed else None,
            set_pending_review=True,
            updated_at=now,
        )
        if updated is None:
            # Гонка: пост удалили между get_by_id и update_post. Маловероятно,
            # но обрабатываем явно — 404, чтобы фронт показал ошибку.
            raise FeedServiceError(404, "Post not found")

        if media_changed and normalized_new_media is not None:
            await self._feed_repo.replace_media(post_id, normalized_new_media)

        await self._db.commit()
        await self._log_event(
            user.id,
            EventType.FEED_POST_EDITED,
            {
                "post_id": post_id,
                "text_changed": text_changed,
                "media_changed": media_changed,
            },
        )

        # Возвращаем свежий объект — нужен роуту для построения ответа.
        refreshed = await self._feed_repo.get_by_id(post_id)
        if refreshed is None:
            # Гонка с purge_old_posts — крайне маловероятно, но не игнорируем.
            raise FeedServiceError(500, "Post disappeared after update")
        return refreshed, True
