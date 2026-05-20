"""Раздел Mini App в боте — единая кнопка открывает Аллею и Ленту.

По нажатию BTN_MINIAPP бот шлёт сообщение с inline-кнопками:
- «Открыть Аллею» — web_app на MINIAPP_URL (/app/)
- «Открыть Ленту» — web_app на MINIAPP_URL + /feed
- «Попасть в аллею» — URL контакта модератора (если настроен)
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.services.analytics_events import EventType
from app.texts import common as common_texts
from app.texts import feed as texts

router = Router(name="miniapp_hub")


class JoinAlleyCb(CallbackData, prefix="join_alley"):
    """Callback кнопки «Попасть в Аллею» когда контакт модератора не настроен."""


def _alley_url() -> str | None:
    """URL Mini App для Аллеи. MINIAPP_URL заканчивается на /app/."""
    base = settings.miniapp_url or ""
    return base if base.startswith("https://") else None


def _feed_url() -> str | None:
    """URL Mini App с маршрутом /feed."""
    base = _alley_url()
    return f"{base.rstrip('/')}/feed" if base else None


@router.message(F.text == common_texts.BTN_MINIAPP)
async def on_miniapp_hub(message: Message, user: User, db_session: AsyncSession) -> None:
    """Открытие раздела «Аллея и Лента» из главного меню."""
    await AnalyticsRepository(db_session).log_event(
        user.id,
        event_type=EventType.CREATORS_ALLEY_OPENED,
    )

    alley_url = _alley_url()
    feed_url = _feed_url()
    if alley_url is None or feed_url is None:
        await message.answer(texts.MINIAPP_NOT_CONFIGURED)
        return

    contact_url = await SettingsRepository(db_session).get("creator_alley_contact_url")

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=texts.BTN_OPEN_ALLEY, web_app=WebAppInfo(url=alley_url))],
        [InlineKeyboardButton(text=texts.BTN_OPEN_FEED, web_app=WebAppInfo(url=feed_url))],
    ]
    # Кнопка «Попасть в Аллею» показывается всегда. Есть контакт модератора —
    # ведёт ссылкой; нет — по callback подскажем обратиться в поддержку.
    if contact_url:
        rows.append([InlineKeyboardButton(text=texts.BTN_JOIN_ALLEY, url=contact_url)])
    else:
        rows.append(
            [InlineKeyboardButton(text=texts.BTN_JOIN_ALLEY, callback_data=JoinAlleyCb().pack())]
        )

    await message.answer(
        texts.HUB_INTRO,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(JoinAlleyCb.filter())
async def on_join_alley_no_contact(callback: CallbackQuery) -> None:
    """Контакт модератора не настроен — подсказываем написать в поддержку."""
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(texts.JOIN_ALLEY_NO_CONTACT)
