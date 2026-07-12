from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models.dictionaries import Vibe

T = TypeVar("T", bound=Base)


class DictionaryRepository:
    """Дженерик-репозиторий для справочников с общей схемой (id/code/title/is_active/sort_order).

    Используется для Gender, Fandom, Interest, CreatorCategory, Vibe, ComplaintReason.
    Все эти модели наследуют `DictionaryMixin` и предоставляют те же столбцы.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self, model: type[T]) -> list[T]:
        stmt = (
            select(model)
            .where(model.is_active.is_(True))  # type: ignore[attr-defined]
            .order_by(model.sort_order, model.id)  # type: ignore[attr-defined]
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_all(self, model: type[T], *, limit: int = 100, offset: int = 0) -> list[T]:
        """Все записи справочника (включая неактивные) — для admin CRUD (10.8)."""
        stmt = (
            select(model)
            .order_by(model.sort_order, model.id)  # type: ignore[attr-defined]
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_id(self, model: type[T], entity_id: int) -> T | None:
        return await self._session.get(model, entity_id)

    async def get_by_code(self, model: type[T], code: str) -> T | None:
        stmt = select(model).where(model.code == code)  # type: ignore[attr-defined]
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_vibe_by_number(self, number: int) -> Vibe | None:
        """Вайб по клиентскому номеру 1..36 (admin-пикер вайбов)."""
        stmt = select(Vibe).where(Vibe.number == number).limit(1)
        return (await self._session.execute(stmt)).scalars().first()

    async def create(self, model: type[T], **fields: Any) -> T:
        """Создаёт запись справочника. Используется в admin CRUD (10.8)."""
        instance = model(**fields)  # type: ignore[call-arg]
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def update_item(self, model: type[T], entity_id: int, **fields: Any) -> T | None:
        """Обновляет поля записи справочника. Используется в admin CRUD (10.8)."""
        await self._session.execute(
            update(model)  # type: ignore[arg-type]
            .where(model.id == entity_id)  # type: ignore[attr-defined]
            .values(**fields)
        )
        await self._session.flush()
        return await self._session.get(model, entity_id)

    async def set_active(self, model: type[T], entity_id: int, *, is_active: bool) -> None:
        """Включает или выключает запись справочника без удаления (10.8)."""
        await self._session.execute(
            update(model)  # type: ignore[arg-type]
            .where(model.id == entity_id)  # type: ignore[attr-defined]
            .values(is_active=is_active)
        )
        await self._session.flush()
