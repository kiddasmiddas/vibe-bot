"""Бизнес-логика авто-рекламы в ленте анкет.

После каждой N-й анкеты (по действиям лайк/дизлайк/скип) не-премиум пользователю
показывается один креатив из пула по кругу. N — настройка `ads_rotation_every_n`.
Премиум рекламу не видит (обещано «Отключение рекламы»).
"""

from __future__ import annotations

from loguru import logger

from app.db.models.ads_rotation import AdRotationPost
from app.db.repositories.ads_rotation_repo import AdsRotationRepository
from app.db.repositories.settings_repo import SettingsRepository

_SETTING_EVERY_N = "ads_rotation_every_n"
_DEFAULT_EVERY_N = 10
# Счётчик просмотров на пользователя живёт в Redis. TTL — чтобы ключи неактивных
# пользователей не копились; для активных счёт продолжается (модуль N не страдает).
_COUNTER_KEY = "ads:seen:{user_id}"
_COUNTER_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 дней


class AdsRotationService:
    """Решает, показывать ли рекламу на текущем шаге, и выбирает креатив."""

    def __init__(
        self,
        *,
        ads_repo: AdsRotationRepository,
        settings_repo: SettingsRepository,
        redis,  # type: ignore[no-untyped-def]  # redis.asyncio.Redis
    ) -> None:
        self._ads_repo = ads_repo
        self._settings_repo = settings_repo
        self._redis = redis

    async def tick_and_pick(self, user_id: int, *, is_premium: bool) -> AdRotationPost | None:
        """Зарегистрировать просмотр анкеты и, если пора, вернуть креатив рекламы.

        Возвращает `AdRotationPost` на каждой N-й анкете (если пул не пуст), иначе `None`.
        Премиум, отключённая реклама (N<=0) и недоступность Redis → `None` (fail-open).
        """
        if is_premium:
            return None

        every_n = await self._settings_repo.get_int(_SETTING_EVERY_N)
        if every_n is None:
            every_n = _DEFAULT_EVERY_N
        if every_n <= 0:
            return None

        key = _COUNTER_KEY.format(user_id=user_id)
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, _COUNTER_TTL_SECONDS)
        except Exception as exc:
            logger.warning("ads rotation: redis counter error, skipping ad: {}", exc)
            return None

        if count % every_n != 0:
            return None

        return await self._ads_repo.pick_next()
