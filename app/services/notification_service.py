"""Троттлинг пуш-уведомлений: лайки анкеты и комментарии к постам Ленты.

Лайки — событийная агрегация без планировщика: первое событие после «тихого»
периода шлёт пуш сразу, события внутри кулдауна копятся в Redis-счётчике и
уходят одним сообщением вместе со следующим событием после истечения кулдауна.

Комментарии — без агрегации: разовый пуш автору поста на каждый комментарий
сразу по факту (решение клиента: комментариев мало, а отложенный «+N новых»
бессмыслен, если автор уже открыл пост сам).

Настройки app_settings (правятся из /admin → Уведомления):
- `notif_like_cooldown_hours` (дефолт 24, 0 = лайк-пуши выключены);
- `notif_comment_push_enabled` (дефолт 1, 0 = коммент-пуши выключены).

Redis недоступен → fail-open: лайк-пушей нет, основной функционал не страдает
(накопленные лайки в любом случае видны в «Кто меня лайкнул»).
"""

from __future__ import annotations

from loguru import logger

from app.db.repositories.settings_repo import SettingsRepository

SETTING_LIKE_COOLDOWN_HOURS = "notif_like_cooldown_hours"
DEFAULT_LIKE_COOLDOWN_HOURS = 24
SETTING_COMMENT_PUSH_ENABLED = "notif_comment_push_enabled"
DEFAULT_COMMENT_PUSH_ENABLED = True

_LIKE_CD_KEY = "notif:like:cd:{user_id}"
_LIKE_PENDING_KEY = "notif:like:pend:{user_id}"
_COMMENT_BURST_KEY = "notif:cburst:{user_id}"
_COMMENT_BURST_SECONDS = 60
# Pending-счётчик должен пережить кулдаун любой разумной длины (админ может
# поставить и неделю), но не копиться вечно у неактивных получателей.
_PENDING_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 дней


class NotificationThrottle:
    """Решает, слать ли пуш на очередное событие, и считает накопленное.

    Чтение настроек — DB-direct (SettingsRepository без redis), чтобы сбой
    Redis не ломал горячие пути и правки админа применялись мгновенно.
    """

    def __init__(
        self,
        *,
        settings_repo: SettingsRepository,
        redis,  # type: ignore[no-untyped-def]  # redis.asyncio.Redis
    ) -> None:
        self._settings_repo = settings_repo
        self._redis = redis

    async def _cooldown_seconds(self, key: str, default: int, multiplier: int) -> int:
        """Читает настройку кулдауна; отрицательные значения считаем нулём."""
        value = await self._settings_repo.get_int(key)
        if value is None:
            value = default
        return max(value, 0) * multiplier

    async def _register(self, cd_key: str, pending_key: str, cooldown_seconds: int) -> int | None:
        """Общая механика: None → молчим; N ≥ 1 → слать пуш про N событий.

        SET NX на cd-ключ атомарно «занимает» окно тишины. Забор pending —
        GET + DELETE без транзакции: гонка двух одновременных событий в худшем
        случае потеряет/задвоит единицу в счётчике пуша, что для уведомлений
        приемлемо и не стоит усложнения.
        """
        try:
            acquired = await self._redis.set(cd_key, 1, ex=cooldown_seconds, nx=True)
            if not acquired:
                await self._redis.incr(pending_key)
                await self._redis.expire(pending_key, _PENDING_TTL_SECONDS)
                return None
            pending_raw = await self._redis.get(pending_key)
            if pending_raw is not None:
                await self._redis.delete(pending_key)
            pending = int(pending_raw) if pending_raw else 0
            return pending + 1
        except Exception as exc:
            logger.warning("notification throttle: redis error, skipping push: {}", exc)
            return None

    async def register_like(self, to_user_id: int) -> int | None:
        """Лайк анкеты. None → пуш не нужен; N — слать пуш про N лайков."""
        cooldown = await self._cooldown_seconds(
            SETTING_LIKE_COOLDOWN_HOURS, DEFAULT_LIKE_COOLDOWN_HOURS, 3600
        )
        if cooldown <= 0:
            return None
        return await self._register(
            _LIKE_CD_KEY.format(user_id=to_user_id),
            _LIKE_PENDING_KEY.format(user_id=to_user_id),
            cooldown,
        )

    async def register_superlike(self, to_user_id: int) -> bool:
        """Суперлайк пушится сразу, вне очереди. True → слать.

        Кулдаун обычных лайков при этом обновляется, чтобы следующий обычный
        лайк не продублировал пуш тут же, — накопление продолжается.
        """
        cooldown = await self._cooldown_seconds(
            SETTING_LIKE_COOLDOWN_HOURS, DEFAULT_LIKE_COOLDOWN_HOURS, 3600
        )
        if cooldown <= 0:
            return False
        try:
            await self._redis.set(_LIKE_CD_KEY.format(user_id=to_user_id), 1, ex=cooldown)
        except Exception as exc:
            logger.warning("notification throttle: redis error, skipping push: {}", exc)
            return False
        return True

    async def comments_enabled(self) -> bool:
        """Включены ли коммент-пуши (тумблер админа; Redis не участвует)."""
        value = await self._settings_repo.get_int(SETTING_COMMENT_PUSH_ENABLED)
        if value is None:
            return DEFAULT_COMMENT_PUSH_ENABLED
        return value > 0

    async def allow_comment_push(self, recipient_user_id: int) -> bool:
        """Анти-всплеск: не чаще 1 коммент/ответ-пуша в минуту на получателя.

        Защита от пуш-харассмента (спамер строчит комменты под постом жертвы —
        без гарда каждый превращался бы в пуш). При обычном темпе (2-3 коммента
        на пост) поведение «разовый пуш по факту» не меняется. Redis недоступен
        → пуш не шлём (fail-open в сторону тишины, как у лайков).
        """
        key = _COMMENT_BURST_KEY.format(user_id=recipient_user_id)
        try:
            return bool(await self._redis.set(key, 1, ex=_COMMENT_BURST_SECONDS, nx=True))
        except Exception as exc:
            logger.warning("notification throttle: redis error, skipping push: {}", exc)
            return False
