from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.settings import AppSetting

# Кэшируем значения в Redis на 60 секунд: достаточно свежо для админских правок,
# но снимает нагрузку с БД при частых апдейтах.
CACHE_TTL_SECONDS = 60
CACHE_KEY_PREFIX = "settings:"


class SettingsRepository:
    """Ключ-значение для продуктовых настроек. Значения всегда строки;
    типизированные геттеры парсят при чтении."""

    def __init__(self, session: AsyncSession, redis=None) -> None:  # type: ignore[no-untyped-def]
        self._session = session
        self._redis = redis  # redis.asyncio.Redis | None

    @staticmethod
    def _cache_key(key: str) -> str:
        return f"{CACHE_KEY_PREFIX}{key}"

    async def get(self, key: str) -> str | None:
        if self._redis is not None:
            cached = await self._redis.get(self._cache_key(key))
            if cached is not None:
                return cached

        stmt = select(AppSetting.value).where(AppSetting.key == key)
        value: str | None = (await self._session.execute(stmt)).scalar_one_or_none()

        if value is not None and self._redis is not None:
            await self._redis.set(self._cache_key(key), value, ex=CACHE_TTL_SECONDS)

        return value

    async def set(self, key: str, value: str, *, by_user_id: int | None = None) -> None:
        stmt = (
            pg_insert(AppSetting)
            .values(key=key, value=value, updated_by_user_id=by_user_id)
            .on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": value, "updated_by_user_id": by_user_id},
            )
        )
        await self._session.execute(stmt)

        if self._redis is not None:
            # Инвалидация — пишем новое значение поверх старого с тем же TTL.
            await self._redis.set(self._cache_key(key), value, ex=CACHE_TTL_SECONDS)

    async def get_int(self, key: str) -> int | None:
        raw = await self.get(key)
        return None if raw is None or raw == "" else int(raw)

    async def get_float(self, key: str) -> float | None:
        raw = await self.get(key)
        return None if raw is None or raw == "" else float(raw)
