"""Раздел «Вайбы» в справочниках: пикер страниц как у пользователей.

Вместо списка из 36 сообщений — экран с коллажем страницы и кнопками 1–9
(3×3) со стрелками навигации, один в один как пикер регистрации. Тап по
номеру открывает карточку вайба (переименовать / вкл-выкл).

Механика «36 вайбов / 4 коллажа» не меняется: коллаж страницы хранится в
image_file_id вайба-«обложки» — первого номера страницы (№1/№10/№19/№28).
Картинка меняется только кнопкой на экране страницы; у отдельных вайбов
картинок в UI больше нет (раньше шаг «пришлите картинку» в редакторе любого
вайба сбивал с толку — заливка на не-обложку ничего не меняла).
"""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import AdminMenuCb, AdminVibesCb, admin_back_home_kb
from app.bot.states.admin import AdminVibesStates
from app.bot.utils.vibe_picker import (
    PAGE_SIZE,
    TOTAL_PAGES,
    fetch_page_image_file_id,
    numbers_for_page,
    page_legend,
)
from app.db.models.dictionaries import Vibe
from app.db.models.user import User
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.texts.admin import (
    ADMIN_MENU_BTN_BACK,
    ADMIN_MENU_BTN_HOME,
    VIBES_ASK_IMAGE,
    VIBES_ASK_TITLE,
    VIBES_BTN_BACK_TO_PAGE,
    VIBES_BTN_DISABLE,
    VIBES_BTN_ENABLE,
    VIBES_BTN_PAGE_IMAGE,
    VIBES_BTN_RENAME,
    VIBES_CARD,
    VIBES_IMAGE_NOT_PHOTO,
    VIBES_IMAGE_UPDATED,
    VIBES_NOT_FOUND,
    VIBES_PAGE_CAPTION,
    VIBES_PAGE_NO_IMAGE,
    VIBES_STATUS_ACTIVE,
    VIBES_STATUS_INACTIVE,
    VIBES_TITLE_EMPTY,
    VIBES_TITLE_UPDATED,
)

router = Router(name="admin.vibes")


def _clamp_page(page: int) -> int:
    return max(0, min(page, TOTAL_PAGES - 1))


def _cover_number(page: int) -> int:
    """Номер вайба-«обложки», хранящего коллаж страницы (№1/№10/№19/№28)."""
    return page * PAGE_SIZE + 1


def _page_kb(page: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in numbers_for_page(page):
        b.button(text=str(n), callback_data=AdminVibesCb(action="open", page=page, number=n))
    # Ряд навигации: ‹ N/4 › (крайние позиции — заглушки, как в юзерском пикере).
    if page > 0:
        b.button(text="‹", callback_data=AdminVibesCb(action="page", page=page - 1))
    else:
        b.button(text=" ", callback_data=AdminVibesCb(action="noop", page=page))
    b.button(text=f"{page + 1}/{TOTAL_PAGES}", callback_data=AdminVibesCb(action="noop", page=page))
    if page < TOTAL_PAGES - 1:
        b.button(text="›", callback_data=AdminVibesCb(action="page", page=page + 1))
    else:
        b.button(text=" ", callback_data=AdminVibesCb(action="noop", page=page))
    b.button(text=VIBES_BTN_PAGE_IMAGE, callback_data=AdminVibesCb(action="image", page=page))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="dicts"))
    b.adjust(3, 3, 3, 3, 1, 1)
    return b.as_markup()


def _card_kb(*, page: int, number: int, is_active: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text=VIBES_BTN_RENAME, callback_data=AdminVibesCb(action="rename", page=page, number=number)
    )
    b.button(
        text=VIBES_BTN_DISABLE if is_active else VIBES_BTN_ENABLE,
        callback_data=AdminVibesCb(action="toggle", page=page, number=number),
    )
    b.button(text=VIBES_BTN_BACK_TO_PAGE, callback_data=AdminVibesCb(action="page", page=page))
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2, 2)
    return b.as_markup()


def _back_to_page_kb(page: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=VIBES_BTN_BACK_TO_PAGE, callback_data=AdminVibesCb(action="page", page=page))
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def _card_text(vibe: Vibe) -> str:
    status = VIBES_STATUS_ACTIVE if vibe.is_active else VIBES_STATUS_INACTIVE
    return VIBES_CARD.format(number=vibe.number, title=escape(vibe.title), status=status)


async def _render_page(message: Message, db_session: AsyncSession, page: int) -> None:
    page = _clamp_page(page)
    image_file_id = await fetch_page_image_file_id(db_session, page)
    caption = VIBES_PAGE_CAPTION.format(page=page + 1, total=TOTAL_PAGES)
    legend = await page_legend(db_session, page, include_inactive=True)
    if legend:
        caption += f"\n\n{legend}"
    if image_file_id is None:
        caption += VIBES_PAGE_NO_IMAGE
    await show_screen(
        message,
        text=caption,
        reply_markup=_page_kb(page),
        media_file_id=image_file_id,
        media_type="photo" if image_file_id else None,
    )


@router.callback_query(AdminVibesCb.filter(F.action == "noop"))
async def cb_vibes_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(AdminVibesCb.filter(F.action == "page"))
async def cb_vibes_page(
    callback: CallbackQuery,
    callback_data: AdminVibesCb,
    user: User,
    db_session: AsyncSession,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await _render_page(callback.message, db_session, callback_data.page)


@router.callback_query(AdminVibesCb.filter(F.action == "open"))
async def cb_vibes_open(
    callback: CallbackQuery,
    callback_data: AdminVibesCb,
    user: User,
    db_session: AsyncSession,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    vibe = await DictionaryRepository(db_session).get_vibe_by_number(callback_data.number)
    if vibe is None:
        await callback.answer(VIBES_NOT_FOUND.format(number=callback_data.number), show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await show_screen(
            callback.message,
            text=_card_text(vibe),
            reply_markup=_card_kb(
                page=callback_data.page, number=vibe.number, is_active=vibe.is_active
            ),
        )


@router.callback_query(AdminVibesCb.filter(F.action == "toggle"))
async def cb_vibes_toggle(
    callback: CallbackQuery,
    callback_data: AdminVibesCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = DictionaryRepository(db_session)
    vibe = await repo.get_vibe_by_number(callback_data.number)
    if vibe is None:
        await callback.answer(VIBES_NOT_FOUND.format(number=callback_data.number), show_alert=True)
        return
    await repo.set_active(Vibe, vibe.id, is_active=not vibe.is_active)
    vibe = await repo.get_vibe_by_number(callback_data.number)
    logger.info(
        "admin {} toggled vibe #{} active={}",
        user.id,
        callback_data.number,
        vibe and vibe.is_active,
    )
    await callback.answer()
    if callback.message and vibe is not None:
        await show_screen(
            callback.message,
            text=_card_text(vibe),
            reply_markup=_card_kb(
                page=callback_data.page, number=vibe.number, is_active=vibe.is_active
            ),
        )


@router.callback_query(AdminVibesCb.filter(F.action == "rename"))
async def cb_vibes_rename(
    callback: CallbackQuery,
    callback_data: AdminVibesCb,
    user: User,
    db_session: AsyncSession,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    vibe = await DictionaryRepository(db_session).get_vibe_by_number(callback_data.number)
    if vibe is None:
        await callback.answer(VIBES_NOT_FOUND.format(number=callback_data.number), show_alert=True)
        return
    await state.set_state(AdminVibesStates.ask_title)
    await state.update_data(vibe_number=callback_data.number, vibe_page=callback_data.page)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            VIBES_ASK_TITLE.format(number=vibe.number, title=escape(vibe.title)),
            reply_markup=admin_back_home_kb(),
        )


@router.message(StateFilter(AdminVibesStates.ask_title), F.text)
async def on_vibes_title(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    title = (message.text or "").strip()
    data = await state.get_data()
    number = int(data.get("vibe_number", 0))
    page = int(data.get("vibe_page", 0))
    if not title:
        await message.answer(VIBES_TITLE_EMPTY, reply_markup=admin_back_home_kb())
        return
    repo = DictionaryRepository(db_session)
    vibe = await repo.get_vibe_by_number(number)
    if vibe is None:
        await state.clear()
        await message.answer(
            VIBES_NOT_FOUND.format(number=number), reply_markup=admin_back_home_kb()
        )
        return
    await repo.update_item(Vibe, vibe.id, title=title)
    await state.clear()
    logger.info("admin {} renamed vibe #{} -> {!r}", user.id, number, title)
    await message.answer(
        VIBES_TITLE_UPDATED.format(number=number, title=escape(title)),
        reply_markup=_back_to_page_kb(page),
    )


@router.callback_query(AdminVibesCb.filter(F.action == "image"))
async def cb_vibes_image(
    callback: CallbackQuery,
    callback_data: AdminVibesCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    page = _clamp_page(callback_data.page)
    numbers = numbers_for_page(page)
    await state.set_state(AdminVibesStates.ask_image)
    await state.update_data(vibe_page=page)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            VIBES_ASK_IMAGE.format(
                page=page + 1, total=TOTAL_PAGES, first=numbers[0], last=numbers[-1]
            ),
            reply_markup=admin_back_home_kb(),
        )


@router.message(StateFilter(AdminVibesStates.ask_image))
async def on_vibes_image(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    if not message.photo:
        await message.answer(VIBES_IMAGE_NOT_PHOTO, reply_markup=admin_back_home_kb())
        return
    data = await state.get_data()
    page = _clamp_page(int(data.get("vibe_page", 0)))
    file_id = message.photo[-1].file_id
    repo = DictionaryRepository(db_session)
    cover = await repo.get_vibe_by_number(_cover_number(page))
    if cover is None:
        await state.clear()
        await message.answer(
            VIBES_NOT_FOUND.format(number=_cover_number(page)), reply_markup=admin_back_home_kb()
        )
        return
    await repo.update_item(Vibe, cover.id, image_file_id=file_id)
    await state.clear()
    logger.info("admin {} set page {} vibe collage (cover #{})", user.id, page + 1, cover.number)
    await message.answer(
        VIBES_IMAGE_UPDATED.format(page=page + 1, total=TOTAL_PAGES),
        reply_markup=_back_to_page_kb(page),
    )
