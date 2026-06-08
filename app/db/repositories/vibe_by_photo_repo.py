"""Репозиторий запросов «Вайб по фото» (Premium-фича).

Список фото хранится в одной строке (через ';'), для удобства миграции
без диалект-специфичных ARRAY-типов. Парсинг — на уровне репозитория.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vibe_by_photo import VibeByPhotoRequest

_PHOTO_SEPARATOR = ";"


def _join_photos(file_ids: list[str]) -> str:
    return _PHOTO_SEPARATOR.join(file_ids)


def split_photo_file_ids(packed: str) -> list[str]:
    """Распаковка photo_file_ids в список. Пустая строка → пустой список."""
    if not packed:
        return []
    return [fid for fid in packed.split(_PHOTO_SEPARATOR) if fid]


class VibeByPhotoRepository:
    """Единственное место с SQL для vibe_by_photo_requests."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_request(
        self,
        *,
        user_id: int,
        origin: str,
        photo_file_ids: list[str],
        profile_id: int | None = None,
    ) -> VibeByPhotoRequest:
        """Создаёт новый запрос со статусом 'pending'."""
        req = VibeByPhotoRequest(
            user_id=user_id,
            origin=origin,
            profile_id=profile_id,
            photo_file_ids=_join_photos(photo_file_ids),
            status="pending",
        )
        self._session.add(req)
        await self._session.flush()
        return req

    async def get_by_id(self, request_id: int) -> VibeByPhotoRequest | None:
        return await self._session.get(VibeByPhotoRequest, request_id)

    async def list_pending(self, *, limit: int = 50) -> list[VibeByPhotoRequest]:
        """Все запросы, ожидающие модератора (сначала самые старые)."""
        stmt = (
            select(VibeByPhotoRequest)
            .where(VibeByPhotoRequest.status == "pending")
            .order_by(VibeByPhotoRequest.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def set_assigned(
        self,
        request_id: int,
        *,
        vibe_id: int,
        admin_user_id: int,
    ) -> VibeByPhotoRequest | None:
        """Помечает запрос как completed и сохраняет назначенный вайб."""
        stmt = (
            update(VibeByPhotoRequest)
            .where(VibeByPhotoRequest.id == request_id)
            .values(
                status="completed",
                assigned_vibe_id=vibe_id,
                assigned_by_admin_id=admin_user_id,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        req = await self._session.get(VibeByPhotoRequest, request_id)
        if req is not None:
            await self._session.refresh(req)
        return req

    async def set_rejected(
        self,
        request_id: int,
        *,
        admin_user_id: int,
    ) -> VibeByPhotoRequest | None:
        """Помечает запрос как rejected (модератор отказал)."""
        stmt = (
            update(VibeByPhotoRequest)
            .where(VibeByPhotoRequest.id == request_id)
            .values(
                status="rejected",
                assigned_by_admin_id=admin_user_id,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        req = await self._session.get(VibeByPhotoRequest, request_id)
        if req is not None:
            await self._session.refresh(req)
        return req

    @staticmethod
    def get_photo_file_ids(request: VibeByPhotoRequest) -> list[str]:
        """Распаковка photo_file_ids у конкретного запроса."""
        return split_photo_file_ids(request.photo_file_ids)
