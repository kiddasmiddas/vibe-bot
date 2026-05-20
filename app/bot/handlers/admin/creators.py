"""Раздел «Аллея» (Creator Posts) в админке (10.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin
from app.bot.keyboards.admin import (
    AdminAlleyCb,
    AdminMenuCb,
    admin_back_home_kb,
    alley_duration_kb,
    alley_main_kb,
    alley_post_kb,
)
from app.bot.states.admin import AdminAlleyStates
from app.db.models.dictionaries import CreatorCategory
from app.db.models.user import User
from app.db.repositories.creator_repo import CreatorRepository
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.texts.admin import (
    ADMIN_MENU_BTN_HOME,
    ALLEY_CREATE_ASK_AUTHOR,
    ALLEY_CREATE_ASK_CATEGORY,
    ALLEY_CREATE_ASK_DESC,
    ALLEY_CREATE_ASK_DURATION,
    ALLEY_CREATE_ASK_LINK,
    ALLEY_CREATE_ASK_PHOTOS,
    ALLEY_CREATED,
    ALLEY_DELETED,
    ALLEY_EXTEND_ASK_DURATION,
    ALLEY_EXTENDED,
    ALLEY_LIST_EMPTY,
    ALLEY_MENU,
    ALLEY_PHOTO_MAX_REACHED,
    ALLEY_PHOTO_REQUIRED,
    ALLEY_PHOTO_SAVED,
    ALLEY_POST_CARD,
    ALLEY_UNPUBLISHED,
)

router = Router(name="admin.creators")


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

_MONTH_DURATIONS: dict[str, int] = {
    "dur_1": 1,
    "dur_3": 3,
    "dur_6": 6,
    "dur_12": 12,
    "extend_1": 1,
    "extend_3": 3,
    "extend_6": 6,
    "extend_12": 12,
}


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #


@router.callback_query(AdminMenuCb.filter(F.action == "alley"))
async def cb_alley_menu(callback: CallbackQuery, user: User) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(ALLEY_MENU, reply_markup=alley_main_kb())


# ------------------------------------------------------------------ #
# List posts
# ------------------------------------------------------------------ #


@router.callback_query(AdminAlleyCb.filter(F.action == "list"))
async def cb_alley_list(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = CreatorRepository(db_session)
    posts = await repo.list_all_posts(limit=20)
    await callback.answer()
    if not callback.message:
        return
    if not posts:
        await callback.message.answer(ALLEY_LIST_EMPTY, reply_markup=admin_back_home_kb())
        return
    for post in posts:
        text = ALLEY_POST_CARD.format(
            id=post.id,
            author=post.author_display_name,
            category_id=post.category_id,
            description=post.description[:80],
            telegram_link=post.telegram_link,
            published="✅" if post.is_published else "❌",
            expires_at=post.expires_at.strftime("%Y-%m-%d") if post.expires_at else "—",
        )
        await callback.message.answer(text, reply_markup=alley_post_kb(post.id), parse_mode="HTML")


# ------------------------------------------------------------------ #
# Create post FSM
# ------------------------------------------------------------------ #


@router.callback_query(AdminAlleyCb.filter(F.action == "create"))
async def cb_alley_create(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminAlleyStates.ask_author)
    await state.update_data(alley_photos=[])
    await callback.answer()
    if callback.message:
        await callback.message.answer(ALLEY_CREATE_ASK_AUTHOR, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAlleyStates.ask_author), F.text)
async def on_alley_author(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(alley_author=message.text)
    await state.set_state(AdminAlleyStates.ask_category)
    # Показываем кнопки категорий
    dict_repo = DictionaryRepository(db_session)
    cats = await dict_repo.list_active(CreatorCategory)
    b = InlineKeyboardBuilder()
    for cat in cats:
        from app.bot.keyboards.admin import AdminAlleyCb as AC

        b.button(text=cat.title, callback_data=AC(action=f"cat_{cat.id}"))
    b.adjust(2)
    b.row(
        InlineKeyboardButton(
            text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu").pack()
        )
    )
    await message.answer(ALLEY_CREATE_ASK_CATEGORY, reply_markup=b.as_markup())


@router.callback_query(AdminAlleyCb.filter(F.action.startswith("cat_")))
async def cb_alley_category(
    callback: CallbackQuery,
    callback_data: AdminAlleyCb,
    state: FSMContext,
    user: User,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    current = await state.get_state()
    if current != AdminAlleyStates.ask_category.state:
        await callback.answer()
        return
    cat_id = int(callback_data.action.split("_", 1)[1])
    await state.update_data(alley_category_id=cat_id)
    await state.set_state(AdminAlleyStates.ask_description)
    await callback.answer()
    if callback.message:
        await callback.message.answer(ALLEY_CREATE_ASK_DESC, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAlleyStates.ask_description), F.text)
async def on_alley_desc(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(alley_description=message.text)
    await state.set_state(AdminAlleyStates.ask_link)
    await message.answer(ALLEY_CREATE_ASK_LINK, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAlleyStates.ask_link), F.text)
async def on_alley_link(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(alley_link=message.text)
    await state.set_state(AdminAlleyStates.uploading_photos)
    await message.answer(ALLEY_CREATE_ASK_PHOTOS, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAlleyStates.uploading_photos), F.photo)
async def on_alley_photo(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    photos: list[str] = data.get("alley_photos", [])
    if len(photos) >= 3:
        await message.answer(ALLEY_PHOTO_MAX_REACHED, reply_markup=admin_back_home_kb())
        return
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(alley_photos=photos)
    await message.answer(ALLEY_PHOTO_SAVED.format(n=len(photos)), reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAlleyStates.uploading_photos), Command("done"))
async def on_alley_photos_done(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    if not data.get("alley_photos"):
        await message.answer(ALLEY_PHOTO_REQUIRED, reply_markup=admin_back_home_kb())
        return
    await state.set_state(AdminAlleyStates.ask_duration)
    await message.answer(ALLEY_CREATE_ASK_DURATION, reply_markup=alley_duration_kb("dur"))


@router.callback_query(AdminAlleyCb.filter(F.action.in_({"dur_1", "dur_3", "dur_6", "dur_12"})))
async def cb_alley_duration(
    callback: CallbackQuery,
    callback_data: AdminAlleyCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    current = await state.get_state()
    if current != AdminAlleyStates.ask_duration.state:
        await callback.answer()
        return

    months = _MONTH_DURATIONS.get(callback_data.action, 1)
    data = await state.get_data()
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(days=30 * months)

    repo = CreatorRepository(db_session)
    post = await repo.create_post(
        author_display_name=data["alley_author"],
        category_id=data["alley_category_id"],
        description=data["alley_description"],
        telegram_link=data["alley_link"],
        published_at=now,
        expires_at=expires_at,
        is_published=True,
        is_pending_review=False,
        created_by_admin_id=user.id,
    )

    for i, file_id in enumerate(data.get("alley_photos", [])):
        await repo.add_photo(post.id, file_id, i)

    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            ALLEY_CREATED.format(id=post.id), reply_markup=admin_back_home_kb()
        )
    logger.info("admin {} created alley post {}", user.id, post.id)


# ------------------------------------------------------------------ #
# Unpublish / Delete / Extend
# ------------------------------------------------------------------ #


@router.callback_query(AdminAlleyCb.filter(F.action == "unpublish"))
async def cb_alley_unpublish(
    callback: CallbackQuery,
    callback_data: AdminAlleyCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = CreatorRepository(db_session)
    await repo.expire_post(callback_data.post_id)
    logger.info("admin {} unpublished post {}", user.id, callback_data.post_id)
    await callback.answer(ALLEY_UNPUBLISHED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminAlleyCb.filter(F.action == "delete"))
async def cb_alley_delete(
    callback: CallbackQuery,
    callback_data: AdminAlleyCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = CreatorRepository(db_session)
    await repo.delete_post(callback_data.post_id)
    logger.info("admin {} deleted post {}", user.id, callback_data.post_id)
    await callback.answer(ALLEY_DELETED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminAlleyCb.filter(F.action == "extend"))
async def cb_alley_extend_start(
    callback: CallbackQuery,
    callback_data: AdminAlleyCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminAlleyStates.extend_ask_duration)
    await state.update_data(extend_post_id=callback_data.post_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            ALLEY_EXTEND_ASK_DURATION, reply_markup=alley_duration_kb("extend")
        )


@router.callback_query(
    AdminAlleyCb.filter(F.action.in_({"extend_1", "extend_3", "extend_6", "extend_12"}))
)
async def cb_alley_extend_confirm(
    callback: CallbackQuery,
    callback_data: AdminAlleyCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    data = await state.get_data()
    post_id = data.get("extend_post_id")
    if not post_id:
        await callback.answer()
        return
    months = _MONTH_DURATIONS.get(callback_data.action, 1)
    repo = CreatorRepository(db_session)
    post = await repo.extend_post(int(post_id), months)
    await state.clear()
    await callback.answer()
    if callback.message and post:
        await callback.message.answer(
            ALLEY_EXTENDED.format(
                expires_at=post.expires_at.strftime("%Y-%m-%d") if post.expires_at else "—"
            ),
            reply_markup=admin_back_home_kb(),
        )
