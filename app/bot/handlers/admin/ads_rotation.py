"""Раздел «Ротация рекламы»: пул авто-рекламы для ленты анкет.

Конструктор: текст → фото (/skip) → выбор кнопки тремя inline-кнопками
(Реклама спонсора → ссылка | Реклама премиума | Без кнопки) → подпись кнопки.
Список пула с открытием/редактированием/удалением. Креативы от админа —
доверенный источник, контент-модерацию не проходят (как promo_posts).
Команду /premium НЕ используем — её перехватывает глобальный premium-хэндлер.
"""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen, truncate_caption
from app.bot.keyboards.admin import AdminMenuCb, AdRotationCb, admin_back_home_kb
from app.bot.states.admin import AdminAdsRotationStates
from app.db.models.ads_rotation import AdRotationPost
from app.db.models.user import User
from app.db.repositories.ads_rotation_repo import AdsRotationRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.texts import ads_rotation as texts
from app.texts.admin import ADMIN_MENU_BTN_BACK, ADMIN_MENU_BTN_HOME

router = Router(name="admin.ads_rotation")

_SETTING_EVERY_N = "ads_rotation_every_n"
_DEFAULT_EVERY_N = 10


async def _current_every_n(db_session: AsyncSession) -> int:
    val = await SettingsRepository(db_session).get_int(_SETTING_EVERY_N)
    return val if val is not None and val > 0 else _DEFAULT_EVERY_N


# ---------------------------------------------------------------------------
# Хелперы рендера
# ---------------------------------------------------------------------------


def _preview(ad: AdRotationPost) -> str:
    """Короткое превью для кнопки списка (plain text, без HTML)."""
    if ad.text:
        t = " ".join(ad.text.split())
        return (t[:30] + "…") if len(t) > 30 else t
    if ad.media_file_id:
        return "🎞 медиа" if ad.media_type in ("video", "animation") else "🖼 фото"
    return texts.PREVIEW_EMPTY


def _button_desc(ad: AdRotationPost) -> str:
    if not ad.button_label:
        return texts.CARD_BUTTON_NONE
    label = escape(ad.button_label)
    if ad.button_target == "premium":
        return texts.CARD_BUTTON_PREMIUM.format(label=label)
    return texts.CARD_BUTTON_URL.format(label=label, url=escape(ad.button_url or ""))


def _card_text(ad: AdRotationPost) -> str:
    return texts.CARD.format(
        id=ad.id,
        shown=ad.shown_count,
        media=ad.media_type or texts.CARD_MEDIA_NONE,
        button=_button_desc(ad),
        text=escape(ad.text) if ad.text else texts.PREVIEW_EMPTY,
    )


def _card_kb(ad_id: int):  # type: ignore[no-untyped-def]
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_EDIT_TEXT, callback_data=AdRotationCb(action="edit_text", ad_id=ad_id))
    b.button(
        text=texts.BTN_EDIT_MEDIA, callback_data=AdRotationCb(action="edit_media", ad_id=ad_id)
    )
    b.button(
        text=texts.BTN_EDIT_BUTTON, callback_data=AdRotationCb(action="edit_button", ad_id=ad_id)
    )
    b.button(text=texts.BTN_DELETE_THIS, callback_data=AdRotationCb(action="delete", ad_id=ad_id))
    b.button(text=texts.BTN_BACK_TO_POOL, callback_data=AdRotationCb(action="menu"))
    b.adjust(3, 1, 1)
    return b.as_markup()


async def _send_card(message: Message, ad: AdRotationPost | None) -> None:
    """Отправляет карточку креатива (с медиа, если есть) + клавиатуру действий.

    `ad is None` — креатив исчез (например, удалён другим админом между открытием
    редактора и сохранением): показываем «не найдено» вместо падения.
    """
    if ad is None:
        await message.answer(texts.NOT_FOUND, reply_markup=admin_back_home_kb())
        return
    text = _card_text(ad)
    kb = _card_kb(ad.id)
    if ad.media_file_id and ad.media_type:
        cap = truncate_caption(text)
        if ad.media_type == "photo":
            await message.answer_photo(ad.media_file_id, caption=cap, reply_markup=kb)
        elif ad.media_type == "video":
            await message.answer_video(ad.media_file_id, caption=cap, reply_markup=kb)
        else:
            await message.answer_animation(ad.media_file_id, caption=cap, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://")) and len(value) <= 2000


# ---------------------------------------------------------------------------
# Меню пула
# ---------------------------------------------------------------------------


@router.callback_query(AdRotationCb.filter(F.action == "menu"))
async def cb_ads_menu(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    repo = AdsRotationRepository(db_session)
    ads = await repo.list_all(limit=50)
    await callback.answer()
    if not callback.message:
        return

    b = InlineKeyboardBuilder()
    for ad in ads:
        b.button(
            text=texts.LIST_ITEM_LABEL.format(id=ad.id, shown=ad.shown_count, preview=_preview(ad)),
            callback_data=AdRotationCb(action="open", ad_id=ad.id),
        )
    b.button(text=texts.BTN_ADD, callback_data=AdRotationCb(action="add"))
    if ads:
        b.button(text=texts.BTN_DELETE, callback_data=AdRotationCb(action="delete_pick"))
    b.button(text=texts.BTN_FREQUENCY, callback_data=AdRotationCb(action="freq"))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="ads"))
    b.adjust(1)
    every_n = await _current_every_n(db_session)
    await show_screen(
        callback.message,
        text=(texts.MENU if ads else texts.MENU_EMPTY).format(n=every_n),
        reply_markup=b.as_markup(),
    )


@router.callback_query(AdRotationCb.filter(F.action == "freq"))
async def cb_ads_freq(
    callback: CallbackQuery, user: User, db_session: AsyncSession, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    every_n = await _current_every_n(db_session)
    await state.set_state(AdminAdsRotationStates.ask_frequency)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            texts.FREQ_SCREEN.format(n=every_n), reply_markup=admin_back_home_kb()
        )


@router.message(StateFilter(AdminAdsRotationStates.ask_frequency), F.text)
async def on_ads_frequency(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    raw = (message.text or "").strip()
    try:
        n = int(raw)
    except ValueError:
        await message.answer(texts.FREQ_INVALID, reply_markup=admin_back_home_kb())
        return
    if n < 1:
        await message.answer(texts.FREQ_INVALID, reply_markup=admin_back_home_kb())
        return
    await SettingsRepository(db_session).set(_SETTING_EVERY_N, str(n), by_user_id=user.id)
    await state.clear()
    logger.info("admin {} set {}={}", user.id, _SETTING_EVERY_N, n)
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_BACK_TO_POOL, callback_data=AdRotationCb(action="menu"))
    await message.answer(texts.FREQ_UPDATED.format(n=n), reply_markup=b.as_markup())


@router.callback_query(AdRotationCb.filter(F.action == "open"))
async def cb_ads_open(
    callback: CallbackQuery,
    callback_data: AdRotationCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = AdsRotationRepository(db_session)
    ad = await repo.get_by_id(callback_data.ad_id)
    await callback.answer()
    if not callback.message:
        return
    if ad is None:
        await callback.message.answer(texts.NOT_FOUND, reply_markup=admin_back_home_kb())
        return
    await _send_card(callback.message, ad)


# ---------------------------------------------------------------------------
# Удаление
# ---------------------------------------------------------------------------


@router.callback_query(AdRotationCb.filter(F.action == "delete_pick"))
async def cb_ads_delete_pick(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = AdsRotationRepository(db_session)
    ads = await repo.list_all(limit=50)
    await callback.answer()
    if not callback.message:
        return
    b = InlineKeyboardBuilder()
    for ad in ads:
        b.button(
            text=texts.LIST_ITEM_LABEL.format(id=ad.id, shown=ad.shown_count, preview=_preview(ad)),
            callback_data=AdRotationCb(action="delete", ad_id=ad.id),
        )
    b.button(text=texts.BTN_BACK_TO_POOL, callback_data=AdRotationCb(action="menu"))
    b.adjust(1)
    await show_screen(callback.message, text=texts.DELETE_PICK_HEADER, reply_markup=b.as_markup())


@router.callback_query(AdRotationCb.filter(F.action == "delete"))
async def cb_ads_delete(
    callback: CallbackQuery,
    callback_data: AdRotationCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = AdsRotationRepository(db_session)
    deleted = await repo.delete(callback_data.ad_id)
    await callback.answer()
    if not callback.message:
        return
    if deleted:
        logger.info("admin {} deleted ad_rotation_post {}", user.id, callback_data.ad_id)
        text = texts.DELETED.format(id=callback_data.ad_id)
    else:
        text = texts.NOT_FOUND
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_BACK_TO_POOL, callback_data=AdRotationCb(action="menu"))
    await callback.message.answer(text, reply_markup=b.as_markup())


# ---------------------------------------------------------------------------
# Конструктор добавления
# ---------------------------------------------------------------------------


@router.callback_query(AdRotationCb.filter(F.action == "add"))
async def cb_ads_add(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await state.set_state(AdminAdsRotationStates.ask_text)
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.ASK_TEXT, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAdsRotationStates.ask_text), Command("skip"))
async def on_ads_text_skip(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(ads_text=None)
    await state.set_state(AdminAdsRotationStates.ask_media)
    await message.answer(texts.ASK_MEDIA, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAdsRotationStates.ask_text), F.text)
async def on_ads_text(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(ads_text=message.text)
    await state.set_state(AdminAdsRotationStates.ask_media)
    await message.answer(texts.ASK_MEDIA, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAdsRotationStates.ask_media), F.photo)
async def on_ads_media_photo(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(ads_media_file_id=message.photo[-1].file_id, ads_media_type="photo")
    await _go_ask_button(message, state)


@router.message(StateFilter(AdminAdsRotationStates.ask_media), F.video)
async def on_ads_media_video(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    if message.video:
        await state.update_data(ads_media_file_id=message.video.file_id, ads_media_type="video")
    await _go_ask_button(message, state)


@router.message(StateFilter(AdminAdsRotationStates.ask_media), F.animation)
async def on_ads_media_animation(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    if message.animation:
        await state.update_data(
            ads_media_file_id=message.animation.file_id, ads_media_type="animation"
        )
    await _go_ask_button(message, state)


@router.message(StateFilter(AdminAdsRotationStates.ask_media), Command("skip"))
async def on_ads_media_skip(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    if not data.get("ads_text"):
        # Ни текста, ни медиа — креатив пустой, нарушит CHECK. Возвращаем в начало.
        await state.set_state(AdminAdsRotationStates.ask_text)
        await message.answer(texts.EMPTY_CONTENT, reply_markup=admin_back_home_kb())
        await message.answer(texts.ASK_TEXT, reply_markup=admin_back_home_kb())
        return
    await state.update_data(ads_media_file_id=None, ads_media_type=None)
    await _go_ask_button(message, state)


def _ask_button_kb():  # type: ignore[no-untyped-def]
    """Три кнопки выбора, что под рекламой: спонсор / премиум / без кнопки."""
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_TARGET_SPONSOR, callback_data=AdRotationCb(action="btn_url"))
    b.button(text=texts.BTN_TARGET_PREMIUM, callback_data=AdRotationCb(action="btn_premium"))
    b.button(text=texts.BTN_TARGET_NONE, callback_data=AdRotationCb(action="btn_none"))
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(1)
    return b.as_markup()


async def _go_ask_button(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminAdsRotationStates.ask_button)
    await message.answer(texts.ASK_BUTTON, reply_markup=_ask_button_kb())


# --- Выбор цели кнопки тремя inline-кнопками (одни и те же в create- и edit-флоу;
#     роутимся по текущему состоянию). /premium как команду НЕ используем — её
#     перехватывает глобальный premium-хэндлер. ---


@router.callback_query(AdRotationCb.filter(F.action == "btn_url"))
async def cb_ads_btn_url(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    cur = await state.get_state()
    if cur not in (
        AdminAdsRotationStates.ask_button.state,
        AdminAdsRotationStates.edit_button.state,
    ):
        await callback.answer()
        return
    # Состояние не меняем — ссылку поймает текстовый хэндлер ask_button/edit_button.
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.ASK_BUTTON_URL, reply_markup=admin_back_home_kb())


@router.callback_query(AdRotationCb.filter(F.action == "btn_premium"))
async def cb_ads_btn_premium(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    cur = await state.get_state()
    if cur == AdminAdsRotationStates.ask_button.state:
        nxt = AdminAdsRotationStates.ask_button_label
    elif cur == AdminAdsRotationStates.edit_button.state:
        nxt = AdminAdsRotationStates.edit_button_label
    else:
        await callback.answer()
        return
    await state.update_data(ads_button_target="premium", ads_button_url=None)
    await state.set_state(nxt)
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.ASK_BUTTON_LABEL, reply_markup=admin_back_home_kb())


@router.callback_query(AdRotationCb.filter(F.action == "btn_none"))
async def cb_ads_btn_none(
    callback: CallbackQuery, user: User, state: FSMContext, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    cur = await state.get_state()
    await callback.answer()
    if callback.message is None:
        return
    if cur == AdminAdsRotationStates.ask_button.state:
        await state.update_data(ads_button_target=None, ads_button_url=None, ads_button_label=None)
        await _finalize_create(callback.message, state, user, db_session)
    elif cur == AdminAdsRotationStates.edit_button.state:
        data = await state.get_data()
        ad_id = data.get("ads_edit_id")
        await state.clear()
        if ad_id is None:
            return
        repo = AdsRotationRepository(db_session)
        ad = await repo.update_fields(ad_id, button_label=None, button_target=None, button_url=None)
        await callback.message.answer(texts.UPDATED.format(id=ad_id))
        await _send_card(callback.message, ad)


@router.message(StateFilter(AdminAdsRotationStates.ask_button), F.text)
async def on_ads_button_link(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    url = (message.text or "").strip()
    if not _looks_like_url(url):
        await message.answer(texts.INVALID_LINK, reply_markup=admin_back_home_kb())
        return
    await state.update_data(ads_button_target="url", ads_button_url=url)
    await state.set_state(AdminAdsRotationStates.ask_button_label)
    await message.answer(texts.ASK_BUTTON_LABEL, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAdsRotationStates.ask_button_label), F.text)
async def on_ads_button_label(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await state.update_data(ads_button_label=(message.text or "").strip()[:64])
    await _finalize_create(message, state, user, db_session)


async def _finalize_create(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    data = await state.get_data()
    repo = AdsRotationRepository(db_session)
    ad = await repo.create(
        text=data.get("ads_text"),
        media_file_id=data.get("ads_media_file_id"),
        media_type=data.get("ads_media_type"),
        button_label=data.get("ads_button_label"),
        button_target=data.get("ads_button_target"),
        button_url=data.get("ads_button_url"),
        created_by_admin_id=user.id,
    )
    await state.clear()
    logger.info("admin {} created ad_rotation_post {}", user.id, ad.id)
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_BACK_TO_POOL, callback_data=AdRotationCb(action="menu"))
    await message.answer(texts.CREATED.format(id=ad.id), reply_markup=b.as_markup())


# ---------------------------------------------------------------------------
# Редактирование отдельных полей
# ---------------------------------------------------------------------------


@router.callback_query(AdRotationCb.filter(F.action == "edit_text"))
async def cb_ads_edit_text(
    callback: CallbackQuery, callback_data: AdRotationCb, user: User, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.update_data(ads_edit_id=callback_data.ad_id)
    await state.set_state(AdminAdsRotationStates.edit_text)
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.ASK_TEXT, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAdsRotationStates.edit_text), F.text)
async def on_ads_edit_text(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    ad_id = data.get("ads_edit_id")
    await state.clear()
    if ad_id is None:
        return
    repo = AdsRotationRepository(db_session)
    ad = await repo.update_fields(ad_id, text=message.text)
    logger.info("admin {} edited ad_rotation_post {} text", user.id, ad_id)
    await message.answer(texts.UPDATED.format(id=ad_id))
    await _send_card(message, ad)


@router.callback_query(AdRotationCb.filter(F.action == "edit_media"))
async def cb_ads_edit_media(
    callback: CallbackQuery, callback_data: AdRotationCb, user: User, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.update_data(ads_edit_id=callback_data.ad_id)
    await state.set_state(AdminAdsRotationStates.edit_media)
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.ASK_MEDIA, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAdsRotationStates.edit_media), F.photo)
async def on_ads_edit_media_photo(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    await _apply_media_edit(message, state, user, db_session, message.photo[-1].file_id, "photo")


@router.message(StateFilter(AdminAdsRotationStates.edit_media), F.video)
async def on_ads_edit_media_video(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user) or message.video is None:
        await state.clear()
        return
    await _apply_media_edit(message, state, user, db_session, message.video.file_id, "video")


@router.message(StateFilter(AdminAdsRotationStates.edit_media), F.animation)
async def on_ads_edit_media_animation(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user) or message.animation is None:
        await state.clear()
        return
    await _apply_media_edit(
        message, state, user, db_session, message.animation.file_id, "animation"
    )


@router.message(StateFilter(AdminAdsRotationStates.edit_media), Command("skip"))
async def on_ads_edit_media_clear(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    ad_id = data.get("ads_edit_id")
    await state.clear()
    if ad_id is None:
        return
    repo = AdsRotationRepository(db_session)
    ad = await repo.get_by_id(ad_id)
    if ad is None:
        await message.answer(texts.NOT_FOUND, reply_markup=admin_back_home_kb())
        return
    if not ad.text:
        # Удаление медиа оставило бы пустой креатив — запрещаем.
        await message.answer(texts.EMPTY_CONTENT, reply_markup=admin_back_home_kb())
        await _send_card(message, ad)
        return
    ad = await repo.update_fields(ad_id, media_file_id=None, media_type=None)
    await message.answer(texts.UPDATED.format(id=ad_id))
    await _send_card(message, ad)


async def _apply_media_edit(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    file_id: str,
    media_type: str,
) -> None:
    data = await state.get_data()
    ad_id = data.get("ads_edit_id")
    await state.clear()
    if ad_id is None:
        return
    repo = AdsRotationRepository(db_session)
    ad = await repo.update_fields(ad_id, media_file_id=file_id, media_type=media_type)
    logger.info("admin {} edited ad_rotation_post {} media", user.id, ad_id)
    await message.answer(texts.UPDATED.format(id=ad_id))
    await _send_card(message, ad)


@router.callback_query(AdRotationCb.filter(F.action == "edit_button"))
async def cb_ads_edit_button(
    callback: CallbackQuery, callback_data: AdRotationCb, user: User, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.update_data(ads_edit_id=callback_data.ad_id)
    await state.set_state(AdminAdsRotationStates.edit_button)
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.ASK_BUTTON, reply_markup=_ask_button_kb())


@router.message(StateFilter(AdminAdsRotationStates.edit_button), F.text)
async def on_ads_edit_button_link(message: Message, state: FSMContext, user: User) -> None:
    if not is_admin(user):
        await state.clear()
        return
    url = (message.text or "").strip()
    if not _looks_like_url(url):
        await message.answer(texts.INVALID_LINK, reply_markup=admin_back_home_kb())
        return
    await state.update_data(ads_button_target="url", ads_button_url=url)
    await state.set_state(AdminAdsRotationStates.edit_button_label)
    await message.answer(texts.ASK_BUTTON_LABEL, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminAdsRotationStates.edit_button_label), F.text)
async def on_ads_edit_button_label(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    ad_id = data.get("ads_edit_id")
    target = data.get("ads_button_target")
    url = data.get("ads_button_url")
    await state.clear()
    if ad_id is None:
        return
    repo = AdsRotationRepository(db_session)
    ad = await repo.update_fields(
        ad_id,
        button_label=(message.text or "").strip()[:64],
        button_target=target,
        button_url=url,
    )
    logger.info("admin {} edited ad_rotation_post {} button", user.id, ad_id)
    await message.answer(texts.UPDATED.format(id=ad_id))
    await _send_card(message, ad)
