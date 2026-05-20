"""Раздел «Реклама» — создание черновика рассылки (10.7).

Запуск рассылки выполняет `broadcast_runner` (APScheduler, раз в минуту):
он подхватывает посты со status='queued' AND scheduled_at<=now(). Для «/now»
хендлер просто ставит scheduled_at=now() — отправка идёт в сессии шедулера.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import (
    AdminMenuCb,
    AdminPromoCb,
    admin_back_home_kb,
    promo_segment_kb,
)
from app.bot.states.admin import AdminPromoStates
from app.db.models.user import User
from app.db.repositories.promo_repo import PromoRepository
from app.db.repositories.user_repo import UserRepository
from app.texts.admin import (
    ADMIN_MENU_BTN_BACK,
    ADMIN_MENU_BTN_HOME,
    ANNOUNCEMENT_CREATE_ASK_MEDIA,
    ANNOUNCEMENT_CREATE_ASK_TEXT,
    ANNOUNCEMENT_LAUNCHED,
    ANNOUNCEMENT_NO_RECIPIENTS,
    PROMO_BTN_CREATE,
    PROMO_BTN_CREATE_ANNOUNCEMENT,
    PROMO_BTN_LIST,
    PROMO_BTN_STATUS,
    PROMO_CREATE_ASK_MEDIA,
    PROMO_CREATE_ASK_SCHEDULE,
    PROMO_CREATE_ASK_SEGMENT,
    PROMO_CREATE_ASK_TEXT,
    PROMO_EMPTY,
    PROMO_LAUNCHED,
    PROMO_LIST_ITEM,
    PROMO_MENU,
    PROMO_SCHEDULE_INVALID,
    PROMO_SCHEDULED,
    PROMO_STATUS,
)

router = Router(name="admin.promo")

_SEGMENT_MAP = {
    "segment_all": "all",
    "segment_free": "free",
    "segment_premium": "premium",
}


@router.callback_query(AdminMenuCb.filter(F.action == "ads"))
async def cb_promo_menu(callback: CallbackQuery, user: User) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    from app.bot.keyboards.admin import AdminPromoCb as PC

    b = InlineKeyboardBuilder()
    b.button(text=PROMO_BTN_CREATE, callback_data=PC(action="create"))
    b.button(text=PROMO_BTN_CREATE_ANNOUNCEMENT, callback_data=PC(action="announcement_create"))
    b.button(text=PROMO_BTN_LIST, callback_data=PC(action="list"))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(1)
    await callback.answer()
    if callback.message:
        await show_screen(callback.message, text=PROMO_MENU, reply_markup=b.as_markup())


@router.callback_query(AdminPromoCb.filter(F.action == "create"))
async def cb_promo_create(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.update_data(promo_kind="promo")
    await state.set_state(AdminPromoStates.ask_text)
    await callback.answer()
    if callback.message:
        await callback.message.answer(PROMO_CREATE_ASK_TEXT, reply_markup=admin_back_home_kb())


@router.callback_query(AdminPromoCb.filter(F.action == "announcement_create"))
async def cb_announcement_create(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.update_data(promo_kind="announcement")
    await state.set_state(AdminPromoStates.ask_text)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            ANNOUNCEMENT_CREATE_ASK_TEXT, reply_markup=admin_back_home_kb()
        )


@router.message(StateFilter(AdminPromoStates.ask_text), F.text)
async def on_promo_text(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(
        promo_text=message.text,
        promo_media_file_id=None,
        promo_media_type=None,
    )
    await state.set_state(AdminPromoStates.ask_media)
    data = await state.get_data()
    if data.get("promo_kind") == "announcement":
        await message.answer(ANNOUNCEMENT_CREATE_ASK_MEDIA, reply_markup=admin_back_home_kb())
    else:
        await message.answer(PROMO_CREATE_ASK_MEDIA, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminPromoStates.ask_media), F.photo)
async def on_promo_media_photo(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    file_id = message.photo[-1].file_id
    await state.update_data(promo_media_file_id=file_id, promo_media_type="photo")
    if await _try_queue_announcement(message, state, user, db_session):
        return
    await state.set_state(AdminPromoStates.ask_segment)
    await message.answer(PROMO_CREATE_ASK_SEGMENT, reply_markup=promo_segment_kb())


@router.message(StateFilter(AdminPromoStates.ask_media), F.video)
async def on_promo_media_video(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    if message.video:
        file_id = message.video.file_id
        await state.update_data(promo_media_file_id=file_id, promo_media_type="video")
    if await _try_queue_announcement(message, state, user, db_session):
        return
    await state.set_state(AdminPromoStates.ask_segment)
    await message.answer(PROMO_CREATE_ASK_SEGMENT, reply_markup=promo_segment_kb())


@router.message(StateFilter(AdminPromoStates.ask_media), F.animation)
async def on_promo_media_animation(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    if message.animation:
        file_id = message.animation.file_id
        await state.update_data(promo_media_file_id=file_id, promo_media_type="animation")
    if await _try_queue_announcement(message, state, user, db_session):
        return
    await state.set_state(AdminPromoStates.ask_segment)
    await message.answer(PROMO_CREATE_ASK_SEGMENT, reply_markup=promo_segment_kb())


@router.message(StateFilter(AdminPromoStates.ask_media), Command("skip"))
async def on_promo_media_skip(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    if await _try_queue_announcement(message, state, user, db_session):
        return
    await state.set_state(AdminPromoStates.ask_segment)
    await message.answer(PROMO_CREATE_ASK_SEGMENT, reply_markup=promo_segment_kb())


async def _try_queue_announcement(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> bool:
    """Для объявления после медиа сразу создаём custom-рассылку всем пользователям."""
    data = await state.get_data()
    if data.get("promo_kind") != "announcement":
        return False

    user_repo = UserRepository(db_session)
    recipients = await user_repo.list_announcement_recipients(exclude_user_id=user.id)
    if not recipients:
        await state.clear()
        await message.answer(ANNOUNCEMENT_NO_RECIPIENTS, reply_markup=admin_back_home_kb())
        return True

    promo_repo = PromoRepository(db_session)
    post = await promo_repo.create_draft(
        title="Объявление",
        text=data["promo_text"],
        media_file_id=data.get("promo_media_file_id"),
        media_type=data.get("promo_media_type"),
        target_segment="custom",
        scheduled_at=datetime.now(tz=UTC),
        created_by_admin_id=user.id,
        status="queued",
    )
    await promo_repo.add_recipients(post.id, [recipient.id for recipient in recipients])
    await state.clear()

    logger.info(
        "admin {} queued announcement {} for {} recipients",
        user.id,
        post.id,
        len(recipients),
    )
    await message.answer(
        ANNOUNCEMENT_LAUNCHED.format(id=post.id, count=len(recipients)),
        reply_markup=admin_back_home_kb(),
    )
    return True


@router.callback_query(
    AdminPromoCb.filter(F.action.in_({"segment_all", "segment_free", "segment_premium"}))
)
async def cb_promo_segment(
    callback: CallbackQuery,
    callback_data: AdminPromoCb,
    state: FSMContext,
    user: User,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    segment = _SEGMENT_MAP.get(callback_data.action, "all")
    await state.update_data(promo_segment=segment)
    await state.set_state(AdminPromoStates.ask_schedule)
    await callback.answer()
    if callback.message:
        await callback.message.answer(PROMO_CREATE_ASK_SCHEDULE, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminPromoStates.ask_schedule), F.text)
async def on_promo_schedule(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return

    text_input = (message.text or "").strip()
    data = await state.get_data()

    scheduled_at: datetime | None = None
    run_now = False

    if text_input.lower() == "/now":
        run_now = True
    else:
        try:
            scheduled_at = datetime.strptime(text_input, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        except ValueError:
            await message.answer(PROMO_SCHEDULE_INVALID, reply_markup=admin_back_home_kb())
            return

    # «/now» => запланировать на текущий момент: broadcast_runner (APScheduler,
    # раз в минуту) подхватит пост со status='queued' AND scheduled_at<=now().
    # Так рассылка идёт в отдельной сессии шедулера, не блокируя хендлер и не
    # вешая транзакцию UserMiddleware на всё время отправки.
    effective_scheduled_at = datetime.now(tz=UTC) if run_now else scheduled_at

    promo_repo = PromoRepository(db_session)
    post = await promo_repo.create_draft(
        text=data["promo_text"],
        media_file_id=data.get("promo_media_file_id"),
        media_type=data.get("promo_media_type"),
        target_segment=data.get("promo_segment", "all"),
        scheduled_at=effective_scheduled_at,
        created_by_admin_id=user.id,
        status="queued",
    )

    await state.clear()

    if run_now:
        logger.info("admin {} queued broadcast {} for immediate send", user.id, post.id)
        await message.answer(PROMO_LAUNCHED.format(id=post.id), reply_markup=admin_back_home_kb())
    else:
        await message.answer(
            PROMO_SCHEDULED.format(
                id=post.id,
                scheduled_at=scheduled_at.strftime("%Y-%m-%d %H:%M") if scheduled_at else "—",
            ),
            reply_markup=admin_back_home_kb(),
        )


@router.callback_query(AdminPromoCb.filter(F.action == "list"))
async def cb_promo_list(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    promo_repo = PromoRepository(db_session)
    posts = await promo_repo.list_by_status("queued", limit=20)
    all_posts = posts + await promo_repo.list_by_status("sent", limit=10)

    await callback.answer()
    if not callback.message:
        return
    if not all_posts:
        await callback.message.answer(PROMO_EMPTY, reply_markup=admin_back_home_kb())
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    from app.bot.keyboards.admin import AdminPromoCb as PC

    for p in all_posts:
        title_or_text = p.title or ((p.text or "")[:40] + "..." if p.text else "(без текста)")
        item_text = PROMO_LIST_ITEM.format(id=p.id, status=p.status, title_or_text=title_or_text)
        b = InlineKeyboardBuilder()
        b.button(text=PROMO_BTN_STATUS, callback_data=PC(action="status", promo_id=p.id))
        b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
        await callback.message.answer(item_text, reply_markup=b.as_markup())


@router.callback_query(AdminPromoCb.filter(F.action == "status"))
async def cb_promo_status(
    callback: CallbackQuery,
    callback_data: AdminPromoCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    promo_repo = PromoRepository(db_session)
    post = await promo_repo.get_by_id(callback_data.promo_id)
    await callback.answer()
    if post and callback.message:
        text = PROMO_STATUS.format(
            id=post.id,
            status=post.status,
            total=post.total_recipients,
            delivered=post.delivered_count,
            failed=post.failed_count,
        )
        await callback.message.answer(text, parse_mode="HTML", reply_markup=admin_back_home_kb())
