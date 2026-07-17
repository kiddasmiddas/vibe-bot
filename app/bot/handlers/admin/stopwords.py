"""Раздел «Стоп-листы» — CRUD для moderation_stop_words (10.8.2)."""

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import (
    AdminMenuCb,
    AdminStopWordCb,
    admin_back_home_kb,
    stopword_list_kb,
    stopword_page_kb,
)
from app.bot.states.admin import AdminStopWordStates
from app.db.models.user import User
from app.db.repositories.admin_repo import AdminRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.texts.admin import (
    ADMIN_MENU_BTN_HOME,
    STOPWORD_STATE_OFF,
    STOPWORD_STATE_ON,
    STOPWORD_TOGGLED,
    STOPWORDS_ADD_ASK_CATEGORY,
    STOPWORDS_ADD_ASK_KIND,
    STOPWORDS_ADD_ASK_PATTERN,
    STOPWORDS_ADDED,
    STOPWORDS_BTN_KIND_REGEX,
    STOPWORDS_BTN_KIND_WORD,
    STOPWORDS_CANCELLED,
    STOPWORDS_EDIT_ASK_PATTERN,
    STOPWORDS_EMPTY,
    STOPWORDS_ITEM,
    STOPWORDS_NOT_FOUND,
    STOPWORDS_PAGE_TITLE,
    STOPWORDS_REGEX_ERROR,
    STOPWORDS_SEARCH_PROMPT,
    STOPWORDS_UPDATED,
)

router = Router(name="admin.stopwords")

_VALID_CATEGORIES = ("hate_speech", "link", "adult_keyword", "other")
_VALID_KINDS = ("word", "regex")
STOPWORDS_PAGE_SIZE = 8


def _render_item(sw) -> str:  # type: ignore[no-untyped-def]
    return STOPWORDS_ITEM.format(
        id=sw.id,
        kind=sw.kind,
        category=sw.category,
        pattern=sw.pattern,
        state="✅" if sw.is_active else "❌",
    )


async def _render_sw_page(callback: CallbackQuery, page: int, db_session: AsyncSession) -> None:
    """Одно сообщение: страница стоп-слов кнопками + навигация (без флуда)."""
    if not callback.message:
        return
    admin_repo = AdminRepository(db_session)
    total = await admin_repo.count_stop_words()
    if total == 0:
        # Пустой список — та же клавиатура пейджера (добавить/поиск/назад) без элементов.
        await show_screen(
            callback.message,
            text=STOPWORDS_EMPTY,
            reply_markup=stopword_page_kb([], 0, 1),
        )
        return

    total_pages = max(1, (total + STOPWORDS_PAGE_SIZE - 1) // STOPWORDS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    words = await admin_repo.list_stop_words(
        limit=STOPWORDS_PAGE_SIZE, offset=page * STOPWORDS_PAGE_SIZE
    )
    page_items = [(sw.id, sw.kind, sw.pattern, sw.is_active) for sw in words]
    await show_screen(
        callback.message,
        text=STOPWORDS_PAGE_TITLE.format(page=page + 1, total=total_pages),
        reply_markup=stopword_page_kb(page_items, page, total_pages),
    )


@router.callback_query(AdminMenuCb.filter(F.action == "stopwords"))
async def cb_stopwords_menu(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    await _render_sw_page(callback, 0, db_session)


@router.callback_query(AdminStopWordCb.filter(F.action == "list"))
async def cb_sw_list(
    callback: CallbackQuery,
    callback_data: AdminStopWordCb,
    user: User,
    db_session: AsyncSession,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    await _render_sw_page(callback, callback_data.page, db_session)


@router.callback_query(AdminStopWordCb.filter(F.action == "noop"))
async def cb_sw_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(AdminStopWordCb.filter(F.action == "open"))
async def cb_sw_open(
    callback: CallbackQuery,
    callback_data: AdminStopWordCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Карточка стоп-слова на месте списка (без нового сообщения)."""
    if not is_admin(user):
        await callback.answer()
        return
    sw = await AdminRepository(db_session).get_stop_word(callback_data.sw_id)
    await callback.answer()
    if not callback.message:
        return
    if not sw:
        await callback.message.answer(STOPWORDS_NOT_FOUND, reply_markup=admin_back_home_kb())
        return
    await show_screen(
        callback.message,
        text=_render_item(sw),
        reply_markup=stopword_list_kb(sw.id, callback_data.page),
    )


@router.callback_query(AdminStopWordCb.filter(F.action == "add"))
async def cb_sw_add_start(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminStopWordStates.ask_pattern)
    await callback.answer()
    if callback.message:
        await callback.message.answer(STOPWORDS_ADD_ASK_PATTERN, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminStopWordStates.ask_pattern), F.text)
async def on_sw_pattern(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(sw_pattern=message.text)
    await state.set_state(AdminStopWordStates.ask_kind)
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    from app.bot.keyboards.admin import AdminStopWordCb as SC

    b = InlineKeyboardBuilder()
    b.button(text=STOPWORDS_BTN_KIND_WORD, callback_data=SC(action="kind_word"))
    b.button(text=STOPWORDS_BTN_KIND_REGEX, callback_data=SC(action="kind_regex"))
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    await message.answer(STOPWORDS_ADD_ASK_KIND, reply_markup=b.as_markup())


@router.callback_query(AdminStopWordCb.filter(F.action.in_({"kind_word", "kind_regex"})))
async def cb_sw_kind(
    callback: CallbackQuery,
    callback_data: AdminStopWordCb,
    state: FSMContext,
    user: User,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    current = await state.get_state()
    if current != AdminStopWordStates.ask_kind.state:
        await callback.answer()
        return
    kind = "word" if callback_data.action == "kind_word" else "regex"

    # Если regex — проверяем компиляцию
    data = await state.get_data()
    pattern = data.get("sw_pattern", "")
    if kind == "regex":
        try:
            re.compile(pattern)
        except re.error as exc:
            await callback.answer(STOPWORDS_REGEX_ERROR.format(error=str(exc)), show_alert=True)
            return

    await state.update_data(sw_kind=kind)
    await state.set_state(AdminStopWordStates.ask_category)
    await callback.answer()

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    from app.bot.keyboards.admin import AdminStopWordCb as SC

    b = InlineKeyboardBuilder()
    for cat in _VALID_CATEGORIES:
        b.button(text=cat, callback_data=SC(action=f"setcat_{cat}"))
    b.adjust(2)
    b.row(
        InlineKeyboardButton(
            text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu").pack()
        )
    )
    if callback.message:
        await callback.message.answer(STOPWORDS_ADD_ASK_CATEGORY, reply_markup=b.as_markup())


@router.callback_query(AdminStopWordCb.filter(F.action.startswith("setcat_")))
async def cb_sw_set_category(
    callback: CallbackQuery,
    callback_data: AdminStopWordCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    current = await state.get_state()
    if current != AdminStopWordStates.ask_category.state:
        await callback.answer()
        return

    category = callback_data.action.split("_", 1)[1]
    if category not in _VALID_CATEGORIES:
        await callback.answer()
        return

    data = await state.get_data()
    pattern = data.get("sw_pattern", "")
    kind = data.get("sw_kind", "word")

    # Финальная проверка regex
    if kind == "regex":
        try:
            re.compile(pattern)
        except re.error as exc:
            await callback.answer(STOPWORDS_REGEX_ERROR.format(error=str(exc)), show_alert=True)
            return

    mod_repo = ModerationRepository(db_session)
    sw = await mod_repo.add_stop_word(
        pattern=pattern,
        kind=kind,
        category=category,
        admin_id=user.id,
    )
    await state.clear()
    logger.info("admin {} added stopword #{}", user.id, sw.id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            STOPWORDS_ADDED.format(id=sw.id), reply_markup=admin_back_home_kb()
        )


@router.callback_query(AdminStopWordCb.filter(F.action == "toggle"))
async def cb_sw_toggle(
    callback: CallbackQuery,
    callback_data: AdminStopWordCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    admin_repo = AdminRepository(db_session)
    sw = await admin_repo.get_stop_word(callback_data.sw_id)
    if not sw:
        await callback.answer(STOPWORDS_NOT_FOUND, show_alert=True)
        return
    mod_repo = ModerationRepository(db_session)
    updated = await mod_repo.update_stop_word(sw.id, admin_id=user.id, is_active=not sw.is_active)
    fresh = updated if updated is not None else sw
    logger.info("admin {} toggled stopword #{} active={}", user.id, fresh.id, fresh.is_active)
    await callback.answer(
        STOPWORD_TOGGLED.format(
            id=fresh.id,
            state=STOPWORD_STATE_ON if fresh.is_active else STOPWORD_STATE_OFF,
        ),
        show_alert=True,
    )
    if callback.message:
        await callback.message.edit_text(
            _render_item(fresh), reply_markup=stopword_list_kb(fresh.id, callback_data.page)
        )


@router.callback_query(AdminStopWordCb.filter(F.action == "edit"))
async def cb_sw_edit_start(
    callback: CallbackQuery,
    callback_data: AdminStopWordCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminStopWordStates.edit_ask_pattern)
    await state.update_data(sw_edit_id=callback_data.sw_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(STOPWORDS_EDIT_ASK_PATTERN, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminStopWordStates.edit_ask_pattern), F.text)
async def on_sw_edit_pattern(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    sw_id = data.get("sw_edit_id")
    await state.clear()

    if text.lower() == "/skip" or not sw_id:
        await message.answer(STOPWORDS_CANCELLED, reply_markup=admin_back_home_kb())
        return

    admin_repo = AdminRepository(db_session)
    sw = await admin_repo.get_stop_word(int(sw_id))
    if not sw:
        await message.answer(STOPWORDS_NOT_FOUND, reply_markup=admin_back_home_kb())
        return

    # Проверяем regex если тип regex
    if sw.kind == "regex":
        try:
            re.compile(text)
        except re.error as exc:
            await message.answer(
                STOPWORDS_REGEX_ERROR.format(error=str(exc)),
                reply_markup=admin_back_home_kb(),
            )
            return

    mod_repo = ModerationRepository(db_session)
    await mod_repo.update_stop_word(int(sw_id), admin_id=user.id, pattern=text)
    logger.info("admin {} updated stopword #{}", user.id, sw_id)
    await message.answer(STOPWORDS_UPDATED, reply_markup=admin_back_home_kb())


@router.callback_query(AdminStopWordCb.filter(F.action == "search"))
async def cb_sw_search_start(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminStopWordStates.search_query)
    await callback.answer()
    if callback.message:
        await callback.message.answer(STOPWORDS_SEARCH_PROMPT, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminStopWordStates.search_query), F.text)
async def on_sw_search(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    query = (message.text or "").strip()
    await state.clear()
    admin_repo = AdminRepository(db_session)
    results = await admin_repo.search_stop_words(query)
    if not results:
        await message.answer(STOPWORDS_NOT_FOUND, reply_markup=admin_back_home_kb())
        return
    for sw in results[:20]:
        await message.answer(_render_item(sw), reply_markup=stopword_list_kb(sw.id))
