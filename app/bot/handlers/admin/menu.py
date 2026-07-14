"""Главное меню админки: /admin → inline-клавиатура (10.2)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.admin._helpers import ensure_admin, is_admin, show_screen
from app.bot.keyboards.admin import (
    AdminMenuCb,
    admin_cat_content_kb,
    admin_cat_moderation_kb,
    admin_cat_users_kb,
    admin_main_menu_kb,
)
from app.db.models.user import User
from app.texts.admin import (
    ADMIN_MENU_TITLE,
    CAT_CONTENT_TITLE,
    CAT_MODERATION_TITLE,
    CAT_USERS_TITLE,
)

router = Router(name="admin.menu")

# Категория верхнего уровня → (заголовок экрана, фабрика клавиатуры).
_CATEGORIES = {
    "cat_moderation": (CAT_MODERATION_TITLE, admin_cat_moderation_kb),
    "cat_users": (CAT_USERS_TITLE, admin_cat_users_kb),
    "cat_content": (CAT_CONTENT_TITLE, admin_cat_content_kb),
}


@router.message(Command("admin"))
async def cmd_admin(message: Message, user: User) -> None:
    """Вход в админку: /admin. Проверяет права по telegram_id."""
    if not await ensure_admin(message, user):
        return
    await message.answer(ADMIN_MENU_TITLE, reply_markup=admin_main_menu_kb())


@router.callback_query(AdminMenuCb.filter(F.action.in_(_CATEGORIES)))
async def cb_open_category(
    callback: CallbackQuery, callback_data: AdminMenuCb, user: User, state: FSMContext
) -> None:
    """Открыть категорию верхнего уровня (Модерация / Пользователи / Контент)."""
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    title, kb_factory = _CATEGORIES[callback_data.action]
    if callback.message:
        await show_screen(callback.message, text=title, reply_markup=kb_factory())


@router.callback_query(AdminMenuCb.filter(F.action == "menu"))
async def cb_back_to_menu(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    """Возврат в главное меню админки из любого раздела.

    Сбрасывает FSM-state: иначе после нажатия «🏠 В админ-меню» из
    FSM-промпта состояние осталось бы висеть и перехватило бы следующий ввод.
    """
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    if callback.message:
        # edit_text падает на сообщениях с медиа (карточки с фото) —
        # в этом случае шлём новое сообщение.
        try:
            await callback.message.edit_text(ADMIN_MENU_TITLE, reply_markup=admin_main_menu_kb())
        except TelegramBadRequest:
            await callback.message.answer(ADMIN_MENU_TITLE, reply_markup=admin_main_menu_kb())
    await callback.answer()
