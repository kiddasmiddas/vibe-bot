"""Репозиторий запросов «Вайб по фото» (Premium-фича).

Список фото хранится в одной строке (через ';'), для удобства миграции
без диалект-специфичных ARRAY-типов. Парсинг — на уровне репозитория.
"""

from __future__ import annotations

from sqlalchemy import and_, delete, or_, select, update
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

    async def get_latest_for_user(self, user_id: int) -> VibeByPhotoRequest | None:
        """Самый свежий запрос пользователя (любой статус).

        Нужен на финализации регистрации: если модератор успел назначить вайб
        (status='completed') пока юзер дозаполнял анкету, забираем
        assigned_vibe_id оттуда.
        """
        stmt = (
            select(VibeByPhotoRequest)
            .where(VibeByPhotoRequest.user_id == user_id)
            .order_by(VibeByPhotoRequest.created_at.desc(), VibeByPhotoRequest.id.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def delete_pending_for_user(self, user_id: int) -> int:
        """Удаляет все pending-запросы пользователя, возвращает число удалённых.

        Вызывается, когда вайб у пользователя появился другим путём (выбрал
        сам в пикере) — заявка исчезает из очереди модераторов. История
        completed/rejected не трогается.
        """
        stmt = delete(VibeByPhotoRequest).where(
            VibeByPhotoRequest.user_id == user_id,
            VibeByPhotoRequest.status == "pending",
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount or 0

    async def list_pending(self, *, limit: int = 50) -> list[VibeByPhotoRequest]:
        """Все запросы, ожидающие модератора (сначала самые старые)."""
        stmt = (
            select(VibeByPhotoRequest)
            .where(VibeByPhotoRequest.status == "pending")
            .order_by(VibeByPhotoRequest.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_neighbor_pending(
        self, current_request_id: int, *, direction: str
    ) -> VibeByPhotoRequest | None:
        """Соседний pending-запрос относительно current_request_id.

        direction='next' — ближайший pending позже текущего по created_at;
        direction='prev' — ближайший pending раньше текущего.
        Если текущий запрос удалён (CASCADE), fallback на самый старый
        pending (для direction='next') или None (для 'prev').
        """
        current = await self._session.get(VibeByPhotoRequest, current_request_id)
        if current is None:
            # Текущий запрос пропал (юзер удалил аккаунт, ON DELETE CASCADE
            # снёс request). Для skip-навигации возвращаем самый старый pending;
            # для prev возвращаем None (некуда возвращаться).
            if direction == "next":
                return await self.get_first_pending()
            return None

        # tie-break по id: если несколько rows вставлены в одной транзакции
        # (func.now() выдаёт одинаковый timestamp), без id сравнение даст None.
        if direction == "next":
            stmt = (
                select(VibeByPhotoRequest)
                .where(
                    VibeByPhotoRequest.status == "pending",
                    or_(
                        VibeByPhotoRequest.created_at > current.created_at,
                        and_(
                            VibeByPhotoRequest.created_at == current.created_at,
                            VibeByPhotoRequest.id > current.id,
                        ),
                    ),
                )
                .order_by(
                    VibeByPhotoRequest.created_at.asc(),
                    VibeByPhotoRequest.id.asc(),
                )
                .limit(1)
            )
        elif direction == "prev":
            stmt = (
                select(VibeByPhotoRequest)
                .where(
                    VibeByPhotoRequest.status == "pending",
                    or_(
                        VibeByPhotoRequest.created_at < current.created_at,
                        and_(
                            VibeByPhotoRequest.created_at == current.created_at,
                            VibeByPhotoRequest.id < current.id,
                        ),
                    ),
                )
                .order_by(
                    VibeByPhotoRequest.created_at.desc(),
                    VibeByPhotoRequest.id.desc(),
                )
                .limit(1)
            )
        else:
            raise ValueError(f"direction must be 'next' or 'prev', got {direction!r}")

        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_first_pending(
        self, *, excluded_id: int | None = None
    ) -> VibeByPhotoRequest | None:
        """Самый старый pending-запрос. ``excluded_id`` исключает конкретный id —
        нужно для auto-advance после pick/reject, чтобы не вернуть тот же
        запрос из-за рассинхрона identity-map и WHERE-фильтра."""
        stmt = select(VibeByPhotoRequest).where(VibeByPhotoRequest.status == "pending")
        if excluded_id is not None:
            stmt = stmt.where(VibeByPhotoRequest.id != excluded_id)
        stmt = stmt.order_by(VibeByPhotoRequest.created_at.asc()).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def set_assigned(
        self,
        request_id: int,
        *,
        vibe_id: int,
        admin_user_id: int,
    ) -> VibeByPhotoRequest | None:
        """Атомарно помечает запрос completed (только если он pending).

        Возвращает обновлённый объект, либо None если запрос уже обработан
        другим модератором (rowcount=0). Это закрывает TOCTOU-окно между
        прочтением статуса в хэндлере и записью.
        """
        stmt = (
            update(VibeByPhotoRequest)
            .where(
                VibeByPhotoRequest.id == request_id,
                VibeByPhotoRequest.status == "pending",
            )
            .values(
                status="completed",
                assigned_vibe_id=vibe_id,
                assigned_by_admin_id=admin_user_id,
            )
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        if result.rowcount == 0:
            return None
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
        """Атомарно помечает запрос rejected (только если он pending).

        Возвращает обновлённый объект, либо None если запрос уже обработан.
        """
        stmt = (
            update(VibeByPhotoRequest)
            .where(
                VibeByPhotoRequest.id == request_id,
                VibeByPhotoRequest.status == "pending",
            )
            .values(
                status="rejected",
                assigned_by_admin_id=admin_user_id,
            )
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        if result.rowcount == 0:
            return None
        req = await self._session.get(VibeByPhotoRequest, request_id)
        if req is not None:
            await self._session.refresh(req)
        return req

    @staticmethod
    def get_photo_file_ids(request: VibeByPhotoRequest) -> list[str]:
        """Распаковка photo_file_ids у конкретного запроса."""
        return split_photo_file_ids(request.photo_file_ids)
