from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.moderation import ContentModerationLog, StopWord

# Версия кэша инкрементируется при любом изменении стоп-листа — старые ключи
# становятся «осиротевшими» и пропускаются при чтении.
_CACHE_VERSION_KEY = "stop_words:version"
_CACHE_TTL_SECONDS = 60


def _cache_key(version: int) -> str:
    return f"stop_words:v{version}"


class ModerationRepository:
    """Стоп-листы и аудит-журнал модерации.

    Для тестов и сценариев без Redis — можно передавать `redis=None`.
    """

    def __init__(self, session: AsyncSession, redis=None) -> None:  # type: ignore[no-untyped-def]
        self._session = session
        self._redis = redis

    # ---------- Стоп-слова ----------

    async def list_active_stop_words(self) -> list[StopWord]:
        if self._redis is not None:
            version = await self._get_or_init_version()
            cached = await self._redis.get(_cache_key(version))
            if cached is not None:
                # В кэше — сериализованный список dict'ов. Превращаем обратно в
                # detached StopWord без привязки к сессии (для read-only использования
                # в content_moderation_service).
                rows: list[dict[str, Any]] = json.loads(cached)
                return [self._hydrate_stop_word(r) for r in rows]

        stmt = (
            select(StopWord)
            .where(StopWord.is_active.is_(True))
            .order_by(StopWord.kind, StopWord.pattern)
        )
        items = list((await self._session.execute(stmt)).scalars().all())

        if self._redis is not None:
            version = await self._get_or_init_version()
            serialized = json.dumps(
                [
                    {
                        "id": item.id,
                        "pattern": item.pattern,
                        "kind": item.kind,
                        "category": item.category,
                    }
                    for item in items
                ]
            )
            await self._redis.set(_cache_key(version), serialized, ex=_CACHE_TTL_SECONDS)

        return items

    async def add_stop_word(
        self,
        *,
        pattern: str,
        kind: str,
        category: str,
        admin_id: int | None = None,
        notes: str | None = None,
    ) -> StopWord:
        word = StopWord(
            pattern=pattern,
            kind=kind,
            category=category,
            notes=notes,
            created_by_admin_id=admin_id,
        )
        self._session.add(word)
        await self._session.flush()
        await self._invalidate_cache()
        return word

    async def update_stop_word(
        self,
        stop_word_id: int,
        *,
        admin_id: int | None = None,
        **fields: Any,
    ) -> StopWord | None:
        values = {**fields, "updated_by_admin_id": admin_id}
        await self._session.execute(
            update(StopWord).where(StopWord.id == stop_word_id).values(**values)
        )
        await self._session.flush()
        await self._invalidate_cache()
        # refresh кэшированного объекта в identity-map — иначе вернём stale.
        obj = await self._session.get(StopWord, stop_word_id)
        if obj is not None:
            await self._session.refresh(obj)
        return obj

    async def deactivate_stop_word(self, stop_word_id: int, *, admin_id: int | None = None) -> None:
        await self._session.execute(
            update(StopWord)
            .where(StopWord.id == stop_word_id)
            .values(is_active=False, updated_by_admin_id=admin_id)
        )
        await self._invalidate_cache()

    async def _get_or_init_version(self) -> int:
        if self._redis is None:
            return 1
        raw = await self._redis.get(_CACHE_VERSION_KEY)
        if raw is None:
            await self._redis.set(_CACHE_VERSION_KEY, "1")
            return 1
        return int(raw)

    async def _invalidate_cache(self) -> None:
        if self._redis is None:
            return
        # INCR атомарно увеличит счётчик; если ключа нет — создастся с 1.
        if hasattr(self._redis, "incr"):
            await self._redis.incr(_CACHE_VERSION_KEY)
        else:
            current = await self._get_or_init_version()
            await self._redis.set(_CACHE_VERSION_KEY, str(current + 1))

    @staticmethod
    def _hydrate_stop_word(data: dict[str, Any]) -> StopWord:
        word = StopWord(
            pattern=data["pattern"],
            kind=data["kind"],
            category=data["category"],
        )
        word.id = data["id"]
        word.is_active = True
        return word

    # ---------- Журнал модерации ----------

    async def log_moderation(
        self,
        *,
        user_id: int | None,
        target_kind: str,
        target_id: int | None,
        check_type: str,
        decision: str,
        reason: str | None = None,
        nsfw_score: float | None = None,
        matched_terms: list[str] | None = None,
    ) -> None:
        """Пишет решение модерации. Никогда не падает: ошибка БД проглатывается."""
        entry = ContentModerationLog(
            user_id=user_id,
            target_kind=target_kind,
            target_id=target_id,
            check_type=check_type,
            decision=decision,
            reason=reason,
            nsfw_score=nsfw_score,
            matched_terms=matched_terms,
        )
        try:
            self._session.add(entry)
            await self._session.flush()
        except SQLAlchemyError as exc:
            logger.error("moderation log write failed (db): {}", exc)
        except Exception as exc:
            logger.error("moderation log write failed: {}", exc)

    async def list_pending_review(
        self,
        target_kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ContentModerationLog]:
        stmt = select(ContentModerationLog).where(ContentModerationLog.decision == "manual_review")
        if target_kind is not None:
            stmt = stmt.where(ContentModerationLog.target_kind == target_kind)
        stmt = stmt.order_by(ContentModerationLog.created_at.desc()).limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).scalars().all())
