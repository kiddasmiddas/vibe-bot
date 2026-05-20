from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from aiogram.types import User as TgUser
from redis.asyncio import Redis

from app.texts import common as texts

# Ключи Redis:
# - throttle:cb:<tg_id>            — TTL 500 мс, защита от двойного клика по кнопке.
# - throttle:rate:<tg_id>          — TTL 60 с, счётчик апдейтов за минуту.
# - throttle:cb:<tg_id>:notified   — TTL 500 мс, уже отправили подсказку про burst.
# - throttle:rate:<tg_id>:notified — TTL 60 с, уже отправили подсказку про rate-limit.
CALLBACK_BURST_KEY = "throttle:cb:{tg_id}"
CALLBACK_BURST_NOTIFIED_KEY = "throttle:cb:{tg_id}:notified"
RATE_LIMIT_KEY = "throttle:rate:{tg_id}"
RATE_LIMIT_NOTIFIED_KEY = "throttle:rate:{tg_id}:notified"

CALLBACK_BURST_TTL_MS = 500
RATE_LIMIT_WINDOW_SEC = 60
RATE_LIMIT_MAX = 20


class ThrottlingMiddleware(BaseMiddleware):
    """Outer middleware, регистрируется первым в `dp.update.outer_middleware`.

    Лимиты:
    - не более 1 callback в 500 мс на пользователя;
    - не более 20 апдейтов в минуту на пользователя.

    Срабатывание = немедленный отказ ДО user/ban-мидлварей и БД-сессии. Уведомление
    пользователю отправляется не больше одного раза за окно троттлинга — повторные
    апдейты во время мьюта молча отбрасываются, чтобы спам не порождал ответный
    трафик от бота. Защищает БД и Telegram-API от лавины при флуде.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        tg_id = tg_user.id
        inner = _unwrap_event(event)

        # Burst-защита только для callback'ов: набор букв подряд — норма,
        # а двойной клик по inline-кнопке — нет.
        if isinstance(inner, CallbackQuery):
            burst_key = CALLBACK_BURST_KEY.format(tg_id=tg_id)
            acquired = await self._redis.set(burst_key, "1", px=CALLBACK_BURST_TTL_MS, nx=True)
            if not acquired:
                await self._notify_once(
                    inner,
                    notified_key=CALLBACK_BURST_NOTIFIED_KEY.format(tg_id=tg_id),
                    ttl_ms=CALLBACK_BURST_TTL_MS,
                    text=texts.THROTTLED_TOO_FAST,
                )
                return None

        rate_key = RATE_LIMIT_KEY.format(tg_id=tg_id)
        count = await self._redis.incr(rate_key)
        if count == 1:
            await self._redis.expire(rate_key, RATE_LIMIT_WINDOW_SEC)
        if count > RATE_LIMIT_MAX:
            await self._notify_once(
                inner,
                notified_key=RATE_LIMIT_NOTIFIED_KEY.format(tg_id=tg_id),
                ttl_sec=RATE_LIMIT_WINDOW_SEC,
                text=texts.THROTTLED_RATE_LIMIT,
            )
            return None

        return await handler(event, data)

    async def _notify_once(
        self,
        inner: TelegramObject | None,
        *,
        notified_key: str,
        text: str,
        ttl_ms: int | None = None,
        ttl_sec: int | None = None,
    ) -> None:
        """Отправляет подсказку, только если в Redis нет флага `notified` для окна.

        Идемпотентно: первая попытка SET NX занимает флаг и шлёт текст; все
        последующие попадания в этот же троттл-окно молча отбрасываются.
        """
        if inner is None:
            return
        acquired = await self._redis.set(
            notified_key,
            "1",
            nx=True,
            px=ttl_ms,
            ex=ttl_sec,
        )
        if not acquired:
            return
        if isinstance(inner, CallbackQuery):
            await inner.answer(text, show_alert=False)
        elif isinstance(inner, Message):
            await inner.answer(text)


def _unwrap_event(event: TelegramObject) -> TelegramObject | None:
    """Достаёт Message / CallbackQuery из Update. Для прочих типов — None."""
    if isinstance(event, Update):
        return event.message or event.callback_query
    return event
