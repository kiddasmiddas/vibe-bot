from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app.texts import common as texts


def main_menu_kb(*, is_registered: bool) -> ReplyKeyboardMarkup:
    """Главное reply-меню бота.

    Для зарегистрированного (профиль есть и `is_completed=True`) — 7 кнопок.
    Для остальных — одна кнопка «Создать анкету», которая ведёт
    в FSM-регистрации (реализация — этап 3).

    «🖼 Вайб по фото» видна всем зарегистрированным; Premium-гейт — на тапе
    (не-премиум получает NOT_PREMIUM — заодно и апсейл фичи).
    """
    builder = ReplyKeyboardBuilder()

    if not is_registered:
        builder.button(text=texts.BTN_CREATE_PROFILE)
        builder.adjust(1)
        return builder.as_markup(resize_keyboard=True)

    builder.button(text=texts.BTN_MY_PROFILE)
    builder.button(text=texts.BTN_SEARCH)
    builder.button(text=texts.BTN_LIKES_MATCHES)
    builder.button(text=texts.BTN_MINIAPP)
    builder.button(text=texts.BTN_PREMIUM)
    builder.button(text=texts.BTN_VIBE_BY_PHOTO_MENU)
    builder.button(text=texts.BTN_SUPPORT)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)
