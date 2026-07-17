"""Раздел «Справочники» (CRUD для fandoms/interests/vibes/cats/reasons) (10.8)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import (
    DICTS_PAGE_SIZE,
    AdminDictCb,
    AdminMenuCb,
    admin_back_home_kb,
    dict_item_kb,
    dict_list_page_kb,
    dicts_menu_kb,
)
from app.bot.states.admin import AdminDictStates
from app.db.models.dictionaries import (
    ComplaintReason,
    CreatorCategory,
    Fandom,
    Interest,
    Vibe,
)
from app.db.models.user import User
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.texts.admin import (
    DICTS_ACTIVATED,
    DICTS_ADD_ASK_CODE,
    DICTS_ADD_ASK_IMAGE,
    DICTS_ADD_ASK_NUMBER,
    DICTS_ADD_ASK_TITLE,
    DICTS_ADDED,
    DICTS_ASK_NUMBER_INVALID,
    DICTS_DEACTIVATED,
    DICTS_EDIT_ASK_IMAGE,
    DICTS_EDIT_ASK_TITLE,
    DICTS_EMPTY,
    DICTS_ERROR_NO_SESSION,
    DICTS_MENU,
    DICTS_NOT_FOUND,
    DICTS_PAGE_TITLE,
    DICTS_UPDATED,
)

router = Router(name="admin.dictionaries")

_MODEL_MAP: dict[str, type] = {
    "fandom": Fandom,
    "interest": Interest,
    "vibe": Vibe,
    "creator_category": CreatorCategory,
    "complaint_reason": ComplaintReason,
}

_MODEL_NAMES: dict[str, str] = {
    "fandom": "Фандомы",
    "interest": "Интересы",
    "vibe": "Вайбы",
    "creator_category": "Категории Аллеи",
    "complaint_reason": "Причины жалоб",
}


@router.callback_query(AdminMenuCb.filter(F.action == "dicts"))
async def cb_dicts_menu(callback: CallbackQuery, user: User) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    if callback.message:
        await show_screen(callback.message, text=DICTS_MENU, reply_markup=dicts_menu_kb())


# «vibes» здесь больше нет: раздел вайбов — пикер страниц (handlers/admin/vibes.py),
# а не список сообщений. Старые open/edit-хэндлеры для model="vibe" неактивны из UI.
async def _render_dict_page(
    callback: CallbackQuery, model_key: str, page: int, db_session: AsyncSession
) -> None:
    """Одно сообщение: страница справочника кнопками + навигация (без флуда)."""
    model_class = _MODEL_MAP[model_key]
    items = await DictionaryRepository(db_session).list_all(model_class)
    if not callback.message:
        return
    if not items:
        await show_screen(callback.message, text=DICTS_EMPTY, reply_markup=dicts_menu_kb())
        return

    total_pages = max(1, (len(items) + DICTS_PAGE_SIZE - 1) // DICTS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * DICTS_PAGE_SIZE
    page_items = [
        (item.id, item.title, item.is_active) for item in items[start : start + DICTS_PAGE_SIZE]
    ]
    name = _MODEL_NAMES.get(model_key, model_key)
    await show_screen(
        callback.message,
        text=DICTS_PAGE_TITLE.format(name=name, page=page + 1, total=total_pages),
        reply_markup=dict_list_page_kb(model_key, page_items, page, total_pages),
    )


@router.callback_query(
    AdminDictCb.filter(F.action.in_({"fandoms", "interests", "cats", "reasons", "page"}))
)
async def cb_dict_list(
    callback: CallbackQuery,
    callback_data: AdminDictCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    if callback_data.model not in _MODEL_MAP:
        await callback.answer()
        return
    await callback.answer()
    await _render_dict_page(callback, callback_data.model, callback_data.page, db_session)


@router.callback_query(AdminDictCb.filter(F.action == "noop"))
async def cb_dict_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(AdminDictCb.filter(F.action == "open"))
async def cb_dict_open(
    callback: CallbackQuery,
    callback_data: AdminDictCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    model_class = _MODEL_MAP.get(callback_data.model)
    if not model_class:
        await callback.answer()
        return
    dict_repo = DictionaryRepository(db_session)
    item = await dict_repo.get_by_id(model_class, callback_data.item_id)
    await callback.answer()
    if not item or not callback.message:
        if callback.message:
            await callback.message.answer(DICTS_NOT_FOUND, reply_markup=admin_back_home_kb())
        return
    text = f"#{item.id} [{item.code}] {item.title} {'✅' if item.is_active else '❌'}"
    # Заменяем список карточкой элемента на месте (без нового сообщения).
    await show_screen(
        callback.message,
        text=text,
        reply_markup=dict_item_kb(
            callback_data.model, item.id, is_active=item.is_active, page=callback_data.page
        ),
    )


@router.callback_query(AdminDictCb.filter(F.action == "deactivate"))
async def cb_dict_deactivate(
    callback: CallbackQuery,
    callback_data: AdminDictCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    model_class = _MODEL_MAP.get(callback_data.model)
    if not model_class:
        await callback.answer()
        return
    dict_repo = DictionaryRepository(db_session)
    await dict_repo.set_active(model_class, callback_data.item_id, is_active=False)
    logger.info("admin {} deactivated {} #{}", user.id, callback_data.model, callback_data.item_id)
    await callback.answer(DICTS_DEACTIVATED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminDictCb.filter(F.action == "activate"))
async def cb_dict_activate(
    callback: CallbackQuery,
    callback_data: AdminDictCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    model_class = _MODEL_MAP.get(callback_data.model)
    if not model_class:
        await callback.answer()
        return
    dict_repo = DictionaryRepository(db_session)
    await dict_repo.set_active(model_class, callback_data.item_id, is_active=True)
    logger.info("admin {} activated {} #{}", user.id, callback_data.model, callback_data.item_id)
    await callback.answer(DICTS_ACTIVATED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminDictCb.filter(F.action == "add"))
async def cb_dict_add_start(
    callback: CallbackQuery,
    callback_data: AdminDictCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminDictStates.ask_code)
    await state.update_data(dict_model=callback_data.model)
    await callback.answer()
    if callback.message:
        await callback.message.answer(DICTS_ADD_ASK_CODE, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminDictStates.ask_code), F.text)
async def on_dict_code(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(dict_code=message.text)
    await state.set_state(AdminDictStates.ask_title)
    await message.answer(DICTS_ADD_ASK_TITLE, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminDictStates.ask_title), F.text)
async def on_dict_title(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    await state.update_data(dict_title=message.text)
    model_key = data.get("dict_model", "")
    if model_key == "vibe":
        await state.set_state(AdminDictStates.ask_number)
        await message.answer(DICTS_ADD_ASK_NUMBER, reply_markup=admin_back_home_kb())
    else:
        await _create_dict_entry(message, state, model_key, db_session=db_session)


@router.message(StateFilter(AdminDictStates.ask_number), F.text)
async def on_dict_number(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    try:
        number = int((message.text or "").strip())
    except ValueError:
        await message.answer(DICTS_ASK_NUMBER_INVALID, reply_markup=admin_back_home_kb())
        return
    await state.update_data(dict_number=number)
    await state.set_state(AdminDictStates.ask_image)
    await message.answer(DICTS_ADD_ASK_IMAGE, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminDictStates.ask_image), F.photo)
async def on_dict_image(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    file_id = message.photo[-1].file_id
    await state.update_data(dict_image_file_id=file_id)
    data = await state.get_data()
    await _create_dict_entry(message, state, data.get("dict_model", "vibe"), db_session=db_session)


async def _create_dict_entry(
    message: Message,
    state: FSMContext,
    model_key: str,
    db_session: AsyncSession | None = None,
) -> None:
    data = await state.get_data()
    if db_session is None:
        # Если нет сессии — нужно получить её из контекста. В этом flow она должна быть.
        await state.clear()
        await message.answer(DICTS_ERROR_NO_SESSION, reply_markup=admin_back_home_kb())
        return

    model_class = _MODEL_MAP.get(model_key)
    if not model_class:
        await state.clear()
        return

    fields: dict = {
        "code": data.get("dict_code", ""),
        "title": data.get("dict_title", ""),
        "is_active": True,
        "sort_order": 0,
    }
    if model_key == "vibe":
        fields["number"] = data.get("dict_number", 0)
        fields["image_file_id"] = data.get("dict_image_file_id", "")

    dict_repo = DictionaryRepository(db_session)
    await dict_repo.create(model_class, **fields)
    await state.clear()
    await message.answer(DICTS_ADDED, reply_markup=admin_back_home_kb())


@router.callback_query(AdminDictCb.filter(F.action == "edit"))
async def cb_dict_edit_start(
    callback: CallbackQuery,
    callback_data: AdminDictCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminDictStates.edit_ask_title)
    await state.update_data(dict_model=callback_data.model, dict_edit_id=callback_data.item_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(DICTS_EDIT_ASK_TITLE, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminDictStates.edit_ask_title), F.text)
async def on_dict_edit_title(
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
    model_key = data.get("dict_model", "")
    item_id = data.get("dict_edit_id")

    if text.lower() != "/skip" and item_id:
        model_class = _MODEL_MAP.get(model_key)
        if model_class:
            dict_repo = DictionaryRepository(db_session)
            await dict_repo.update_item(model_class, int(item_id), title=text)

    if model_key == "vibe":
        await state.set_state(AdminDictStates.edit_ask_image)
        await message.answer(DICTS_EDIT_ASK_IMAGE, reply_markup=admin_back_home_kb())
    else:
        await state.clear()
        await message.answer(DICTS_UPDATED, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminDictStates.edit_ask_image))
async def on_dict_edit_image(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    item_id = data.get("dict_edit_id")
    if message.photo and item_id:
        file_id = message.photo[-1].file_id
        dict_repo = DictionaryRepository(db_session)
        await dict_repo.update_item(Vibe, int(item_id), image_file_id=file_id)
    await state.clear()
    await message.answer(DICTS_UPDATED, reply_markup=admin_back_home_kb())
