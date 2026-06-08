"""Утилиты для multi-select экранов (фандомы, интересы, looking_for_genders).

Помощник для обновления inline-клавиатуры существующего сообщения через
`edit_reply_markup` — без «миганий» которые были при delete+resend.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

# Оба — keyword-only `page=...`, Callable[...] не выражает kw-only;
# используем гибкий `...`-protocol.
BuildKbCallback = Callable[..., Awaitable[InlineKeyboardMarkup]]
OnPageCallback = Callable[..., Awaitable[None]]


async def refresh_multi_select_kb(
    callback: CallbackQuery,
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int,
    on_build_kb: BuildKbCallback | None,
    on_page: OnPageCallback,
) -> None:
    """Обновляет inline-клавиатуру существующего сообщения мульти-выбора.

    Сначала пытается `edit_reply_markup` (без миганий — текст экрана при
    toggle/page не меняется). Если Telegram отвечает «message is not
    modified» — игнорируем (повторный тап на ту же страницу). На любую
    другую ошибку — fallback: delete + resend через `on_page`.
    Обе ветки fallback защищены try/except: если бот заблокирован
    (`TelegramForbiddenError`) или сообщение протухло — не пробрасываем
    исключение наружу (callback-handler не должен валиться).
    """
    if callback.message is None:
        return
    if on_build_kb is not None:
        new_kb = await on_build_kb(state, db_session, page=page)
        try:
            await callback.message.edit_reply_markup(reply_markup=new_kb)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            logger.debug("multi-select edit failed, fallback to resend: {}", exc)
        except TelegramAPIError as exc:
            logger.debug("multi-select edit failed, fallback to resend: {}", exc)
    # Fallback: старая логика delete + resend. Защищаем оба шага от любых
    # сетевых/прав-доступных ошибок — это callback-handler, наружу не валим.
    try:
        await callback.message.delete()
    except TelegramAPIError:
        pass
    try:
        await on_page(callback.message, state, db_session, page=page)
    except TelegramAPIError as exc:
        logger.warning("multi-select resend failed: {}", exc)
