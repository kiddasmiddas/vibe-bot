from __future__ import annotations

from loguru import logger
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.settings import AppSetting

# Кэшируем значения в Redis на 60 секунд: достаточно свежо для админских правок,
# но снимает нагрузку с БД при частых апдейтах.
CACHE_TTL_SECONDS = 60
CACHE_KEY_PREFIX = "settings:"

# Ключи продуктовых настроек, читаемых сервисами.
# `like_daily_limit` — дневной лимит лайков для обычных пользователей.
# Заведён в seed-миграции b1c4d7e8a2f3; Premium-доступ снимает ограничение.
SETTING_LIKE_DAILY_LIMIT = "like_daily_limit"
DEFAULT_LIKE_DAILY_LIMIT = 30

# Лимиты анкеты (правятся в /admin → ⚙️ Настройки → 📏 Лимиты анкеты).
# `fandoms_max_selected` — максимум выбранных фандомов, и «своих», и «ищу».
# `bio_max_length` — максимум символов «О себе» (сид d96deed7e5da, 500→200).
SETTING_FANDOMS_MAX_SELECTED = "fandoms_max_selected"
DEFAULT_FANDOMS_MAX_SELECTED = 15
SETTING_BIO_MAX_LENGTH = "bio_max_length"
DEFAULT_BIO_MAX_LENGTH = 200


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

    async def delete(self, key: str) -> None:
        """Удаляет ключ (для «вернуть дефолт»); отсутствие записи = дефолт кода."""
        await self._session.execute(sa_delete(AppSetting).where(AppSetting.key == key))
        if self._redis is not None:
            await self._redis.delete(self._cache_key(key))

    async def get_int(self, key: str) -> int | None:
        raw = await self.get(key)
        if raw is None or raw == "":
            return None
        # Значение могло быть сохранено руками через /admin с опечаткой
        # ("200 ", "abc"). Не роняем вызывающий код (в т.ч. начисление Premium
        # после оплаты) — трактуем кривое значение как «нет значения».
        try:
            return int(raw.strip())
        except (ValueError, AttributeError):
            logger.warning("settings.get_int: non-int value for key {!r}: {!r}", key, raw)
            return None

    async def get_float(self, key: str) -> float | None:
        raw = await self.get(key)
        if raw is None or raw == "":
            return None
        try:
            return float(raw.strip())
        except (ValueError, AttributeError):
            logger.warning("settings.get_float: non-float value for key {!r}: {!r}", key, raw)
            return None
