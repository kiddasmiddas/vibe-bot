"""Раздел «Моя анкета» (этап 3.4): просмотр и редактирование.

Отдельный роутер. Каждое поле редактируется собственной мини-FSM
(ProfileEditStates). Удаление — двухшаговое подтверждение, после которого
профиль и все социальные данные пользователя физически удаляются. Аккаунт
и статус сохраняются — пользователь может создать анкету заново.
"""

from __future__ import annotations

from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin.vibe_by_photo import dispatch_vbp_request
from app.bot.keyboards.main_menu import main_menu_kb
from app.bot.keyboards.profile_edit import (
    ProfileEditCb,
    confirm_delete_kb,
    profile_card_kb,
    profile_fields_kb,
)
from app.bot.keyboards.registration import (
    CityCb,
    CityKeepCb,
    GenderCb,
    RegBackCb,
    VibeAnyCb,
    VibeByPhotoCancelCb,
    VibeByPhotoDoneCb,
    VibeByPhotoStartCb,
    VibeDoneCb,
    VibePageCb,
    VibePickCb,
    city_suggestions_kb,
    gender_kb,
    vibe_by_photo_upload_kb,
)
from app.bot.states.profile_edit import ProfileEditStates
from app.bot.utils.admin_notify import notify_admins_profile_pending
from app.bot.utils.media_limits import photo_size_exceeded
from app.bot.utils.multi_select import refresh_multi_select_kb as _refresh_multi_select_kb
from app.bot.utils.pagination import MultiSelectCb, build_multi_select_kb
from app.bot.utils.render_profile import render_profile_card, send_premium_media
from app.bot.utils.vibe_picker import edit_vibe_picker, send_vibe_picker
from app.db.models.dictionaries import Fandom, Gender, Interest, Vibe
from app.db.models.profile import Profile
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.db.repositories.vibe_by_photo_repo import VibeByPhotoRepository
from app.services.access import has_premium_access
from app.services.analytics_events import EventType
from app.services.content_moderation_service import ContentModerationService
from app.services.geo_service import get_geo_service
from app.services.user_service import delete_user_data
from app.texts import common as common_texts
from app.texts import premium_media as pm_texts
from app.texts import profile_edit as texts
from app.texts import registration as reg_texts
from app.texts import vibe_by_photo as vbp_texts

router = Router(name="profile")

# Совпадает с defaults из registration.py (намеренная дубликация,
# чтобы не зависеть от внутренних имён модуля регистрации).
_DEFAULT_NICKNAME_MIN = 2
_DEFAULT_NICKNAME_MAX = 32
_DEFAULT_MIN_AGE = 14
_DEFAULT_MAX_AGE = 80
_DEFAULT_BIO_MAX = 500


# ----------------------------- helpers -----------------------------


def _moderation_service(db_session: AsyncSession) -> ContentModerationService:
    return ContentModerationService(ModerationRepository(db_session))


def _moderation_error_text(reason: str | None) -> str:
    if reason == "link_detected":
        return reg_texts.MODERATION_REJECTED_LINK
    return reg_texts.MODERATION_REJECTED_STOP_WORD


async def _log_edited(db_session: AsyncSession, user_id: int, field: str) -> None:
    await AnalyticsRepository(db_session).log_event(
        user_id,
        event_type=EventType.PROFILE_EDITED,
        payload={"field": field},
    )


async def _send_card(
    message: Message,
    db_session: AsyncSession,
    bot: Bot,
    profile: Profile,
) -> None:
    """Шлёт медиа-карточку «Моя анкета» с inline-клавиатурой редактирования."""
    dict_repo = DictionaryRepository(db_session)
    profile_repo = ProfileRepository(db_session)

    gender = await dict_repo.get_by_id(Gender, profile.gender_id)
    # own_vibe_id IS NULL — вайб ещё подбирает модератор, рендерим заглушку.
    own_vibe = (
        await dict_repo.get_by_id(Vibe, profile.own_vibe_id)
        if profile.own_vibe_id is not None
        else None
    )

    desired_vibe_ids = set(await profile_repo.get_desired_vibe_ids(profile.id))
    all_vibes = await dict_repo.list_active(Vibe)
    desired_vibes = [v for v in all_vibes if v.id in desired_vibe_ids]

    all_fandoms = await dict_repo.list_active(Fandom)
    all_interests = await dict_repo.list_active(Interest)
    all_genders = await dict_repo.list_active(Gender)

    fandom_ids = set(await profile_repo.get_fandom_ids(profile.id))
    desired_fandom_ids = set(await profile_repo.get_desired_fandom_ids(profile.id))
    interest_ids = set(await profile_repo.get_interest_ids(profile.id))
    lfg_ids = set(await profile_repo.get_looking_for_gender_ids(profile.id))

    fandoms = [f for f in all_fandoms if f.id in fandom_ids]
    desired_fandoms = [f for f in all_fandoms if f.id in desired_fandom_ids]
    interests = [i for i in all_interests if i.id in interest_ids]
    looking_for_genders = [g for g in all_genders if g.id in lfg_ids]

    # Только gender обязателен; own_vibe=None — валидное «ждёт модератора».
    if gender is None or (profile.own_vibe_id is not None and own_vibe is None):
        logger.error(
            "Missing dictionary entries when rendering my-profile for user_id={}",
            profile.user_id,
        )
        await message.answer(reg_texts.PROFILE_SAVE_FAILED)
        return

    rendered = render_profile_card(
        profile,
        gender=gender,
        own_vibe=own_vibe,
        desired_vibes=desired_vibes,
        fandoms=fandoms,
        desired_fandoms=desired_fandoms,
        interests=interests,
        looking_for_genders=looking_for_genders,
        viewer_is_self=True,
    )

    caption = f"{texts.CARD_HEADER}\n{rendered.text}"
    kb = profile_card_kb(
        is_hidden=profile.is_hidden,
        has_music=bool(profile.music_file_id),
        has_video_note=bool(profile.video_note_file_id),
    )
    chat_id = message.chat.id

    try:
        if rendered.media_type == "photo":
            await bot.send_photo(chat_id, rendered.media_file_id, caption=caption, reply_markup=kb)
        elif rendered.media_type == "video":
            await bot.send_video(chat_id, rendered.media_file_id, caption=caption, reply_markup=kb)
        elif rendered.media_type == "gif":
            await bot.send_animation(
                chat_id, rendered.media_file_id, caption=caption, reply_markup=kb
            )
        else:
            await message.answer(caption, reply_markup=kb)
    except Exception as exc:  # pragma: no cover — медиа-отправка не критична
        logger.warning("Failed to send my-profile media: {}", exc)
        await message.answer(caption, reply_markup=kb)

    await send_premium_media(bot, chat_id, profile, db_session, with_premium_media=True)


# ----------------------------- entry: «Моя анкета» -----------------------------


@router.message(Command("cancel"), StateFilter(ProfileEditStates))
async def cmd_cancel_edit(message: Message, state: FSMContext) -> None:
    """`/cancel` во время мини-FSM редактирования — выйти и сообщить пользователю.

    Без этого хэндлера команда могла попасть в общий обработчик и оставить
    пользователя застрявшим в state редактирования.
    """
    await state.clear()
    await message.answer(texts.EDIT_CANCELLED)


@router.message(F.text == common_texts.BTN_MY_PROFILE)
async def on_my_profile(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    await state.clear()
    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None or not profile.is_completed:
        await message.answer(
            texts.NO_PROFILE_YET,
            reply_markup=main_menu_kb(is_registered=False),
        )
        return
    await _send_card(message, db_session, bot, profile)

    # Мягкая подсказка для старых профилей без города.
    if profile.city is None:
        builder = InlineKeyboardBuilder()
        builder.button(
            text=texts.BTN_FILL_CITY,
            callback_data=ProfileEditCb(action="city"),
        )
        await message.answer(texts.CITY_MISSING_HINT, reply_markup=builder.as_markup())

    # Подсказка для пользователей с устаревшим выбором вайбов.
    if profile.vibes_need_review:
        await message.answer(texts.VIBES_NEED_REVIEW_HINT)


# ----------------------------- dispatcher: ProfileEditCb -----------------------------


@router.callback_query(ProfileEditCb.filter())
async def on_profile_edit_dispatch(
    callback: CallbackQuery,
    callback_data: ProfileEditCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Общий вход для всех действий с карточкой «Моя анкета».

    Узкие хэндлеры (на конкретные FSM-state) висят отдельно — здесь только
    запуск мини-FSM из карточки и обработка toggle/delete/confirm/cancel.
    """
    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    action = callback_data.action

    # confirm/cancel/delete — единственные действия, которые могут происходить
    # в FSM (confirm_delete), но обработчик всё равно один и тот же.
    if action == "cancel_delete":
        await callback.answer()
        await state.clear()
        if profile is not None and callback.message is not None:
            await _send_card(callback.message, db_session, bot, profile)
        return

    if action == "confirm_delete":
        # Защита от случайного срабатывания по старой кнопке из истории чата:
        # подтверждение принимается ТОЛЬКО если пользователь сейчас в FSM-state
        # confirm_delete (попал туда через свежий «Удалить анкету» → confirm_delete_kb).
        current_state = await state.get_state()
        if current_state != ProfileEditStates.confirm_delete.state:
            await callback.answer(texts.CONFIRM_DELETE_EXPIRED, show_alert=True)
            return
        await _do_delete_profile(callback, state, user, db_session)
        return

    if profile is None:
        await callback.answer(texts.NO_PROFILE_YET, show_alert=True)
        return

    # Переключение клавиатуры карточки: компактная ⇄ 12 кнопок полей.
    # Меняем только reply_markup у того же сообщения — карточку не перешлём.
    if action == "edit_fields":
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=profile_fields_kb())
        return

    if action == "back_to_card":
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_reply_markup(
                reply_markup=profile_card_kb(
                    is_hidden=profile.is_hidden,
                    has_music=bool(profile.music_file_id),
                    has_video_note=bool(profile.video_note_file_id),
                )
            )
        return

    if action == "toggle_hidden":
        new_hidden = not profile.is_hidden
        await ProfileRepository(db_session).set_hidden(profile.id, new_hidden)
        await db_session.flush()
        await db_session.refresh(profile)
        await _log_edited(db_session, user.id, "is_hidden")
        await callback.answer(texts.HIDDEN_OK if new_hidden else texts.SHOWN_OK)
        if callback.message is not None:
            await _send_card(callback.message, db_session, bot, profile)
        return

    if action == "delete":
        await callback.answer()
        await state.set_state(ProfileEditStates.confirm_delete)
        if callback.message is not None:
            await callback.message.answer(
                texts.CONFIRM_DELETE_WARNING,
                reply_markup=confirm_delete_kb(),
            )
        return

    # Premium-медиа: проверяем доступ ДО unconditional callback.answer().
    # show_alert=True требует единственного вызова answer на весь обработчик.
    if action in ("add_music", "remove_music", "add_video_note", "remove_video_note"):
        if not has_premium_access(user):
            await callback.answer(pm_texts.NEED_PREMIUM, show_alert=True)
            return

        # Доступ есть (Premium или админ) — продолжаем.
        await callback.answer()
        msg = callback.message
        if msg is None:
            return

        if action == "add_music":
            await msg.answer(pm_texts.MUSIC_INSTRUCTION)
            await state.set_state(ProfileEditStates.waiting_music)
            return

        if action == "remove_music":
            await ProfileRepository(db_session).set_music(profile.id, None)
            await db_session.flush()
            await db_session.refresh(profile)
            await _send_card(msg, db_session, bot, await _reload(db_session, profile.id))
            return

        if action == "add_video_note":
            await msg.answer(pm_texts.VIDEO_NOTE_INSTRUCTION)
            await state.set_state(ProfileEditStates.waiting_video_note)
            return

        if action == "remove_video_note":
            await ProfileRepository(db_session).set_video_note(profile.id, None)
            await db_session.flush()
            await db_session.refresh(profile)
            await _send_card(msg, db_session, bot, await _reload(db_session, profile.id))
            return

    # Запуск мини-FSM редактирования отдельного поля.
    await callback.answer()
    msg = callback.message
    if msg is None:
        return

    if action == "nickname":
        await msg.answer(reg_texts.ASK_NICKNAME)
        await state.set_state(ProfileEditStates.edit_nickname)
        return

    if action == "age":
        await msg.answer(reg_texts.ASK_AGE)
        await state.set_state(ProfileEditStates.edit_age)
        return

    if action == "gender":
        genders = await DictionaryRepository(db_session).list_active(Gender)
        await msg.answer(reg_texts.ASK_GENDER, reply_markup=gender_kb(genders))
        await state.set_state(ProfileEditStates.edit_gender)
        return

    if action == "looking_for_genders":
        current = await ProfileRepository(db_session).get_looking_for_gender_ids(profile.id)
        await state.update_data(looking_for_gender_ids=list(current), looking_for_gender_page=0)
        await _send_lfg_screen(msg, state, db_session)
        await state.set_state(ProfileEditStates.edit_looking_for_genders)
        return

    if action == "la_range":
        await msg.answer(reg_texts.ASK_LOOKING_FOR_AGE_MIN)
        await state.set_state(ProfileEditStates.edit_la_min)
        return

    if action == "bio":
        await msg.answer(reg_texts.ASK_BIO)
        await state.set_state(ProfileEditStates.edit_bio)
        return

    if action == "city":
        await msg.answer(reg_texts.ASK_CITY)
        await state.set_state(ProfileEditStates.edit_city)
        return

    if action == "fandoms":
        current = await ProfileRepository(db_session).get_fandom_ids(profile.id)
        await state.update_data(fandom_ids=list(current), fandom_page=0)
        await _send_fandoms_screen(msg, state, db_session)
        await state.set_state(ProfileEditStates.edit_fandoms)
        return

    if action == "desired_fandoms":
        current = await ProfileRepository(db_session).get_desired_fandom_ids(profile.id)
        await state.update_data(desired_fandom_ids=list(current), desired_fandom_page=0)
        await _send_desired_fandoms_screen(msg, state, db_session)
        await state.set_state(ProfileEditStates.edit_desired_fandoms)
        return

    if action == "interests":
        current = await ProfileRepository(db_session).get_interest_ids(profile.id)
        await state.update_data(interest_ids=list(current), interest_page=0)
        await _send_interests_screen(msg, state, db_session)
        await state.set_state(ProfileEditStates.edit_interests)
        return

    if action == "own_vibe":
        vibes = await DictionaryRepository(db_session).list_active(Vibe)
        if not vibes:
            return
        if msg.bot is None:
            return
        show_vbp = has_premium_access(user)
        await send_vibe_picker(
            msg.bot,
            msg.chat.id,
            db_session,
            role="own",
            page=0,
            show_vibe_by_photo=show_vbp,
            vibe_by_photo_origin="profile_edit",
        )
        await state.update_data(vbp_premium=show_vbp)
        await state.set_state(ProfileEditStates.edit_own_vibe)
        return

    if action == "desired_vibe":
        vibes = await DictionaryRepository(db_session).list_active(Vibe)
        if not vibes:
            return
        if msg.bot is None:
            return
        # Подгружаем текущие выбранные номера для pre-select.
        current_ids = set(await ProfileRepository(db_session).get_desired_vibe_ids(profile.id))
        current_numbers = [v.number for v in vibes if v.id in current_ids]
        await state.update_data(desired_vibe_numbers=current_numbers)
        await send_vibe_picker(
            msg.bot,
            msg.chat.id,
            db_session,
            role="desired",
            page=0,
            selected_numbers=set(current_numbers),
        )
        await state.set_state(ProfileEditStates.edit_desired_vibe)
        return

    if action == "media":
        await msg.answer(reg_texts.ASK_MEDIA)
        await state.set_state(ProfileEditStates.edit_media)
        return


# ----------------------------- edit_nickname -----------------------------


@router.message(ProfileEditStates.edit_nickname, F.text)
async def on_edit_nickname(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    text = (message.text or "").strip()
    settings_repo = SettingsRepository(db_session)
    min_len = (await settings_repo.get_int("nickname_min_length")) or _DEFAULT_NICKNAME_MIN
    max_len = (await settings_repo.get_int("nickname_max_length")) or _DEFAULT_NICKNAME_MAX

    if len(text) < min_len:
        await message.answer(reg_texts.NICKNAME_TOO_SHORT.format(min_len=min_len))
        return
    if len(text) > max_len:
        await message.answer(reg_texts.NICKNAME_TOO_LONG.format(max_len=max_len))
        return

    moderation = _moderation_service(db_session)
    result = await moderation.check_text(
        text,
        allow_links=False,
        target_kind="profile_nickname",
        user_id=user.id,
    )
    if not result.approved:
        await message.answer(_moderation_error_text(result.reason))
        return

    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        return
    await ProfileRepository(db_session).update(profile.id, nickname=text)
    await _log_edited(db_session, user.id, "nickname")
    await state.clear()
    await message.answer(texts.EDITED_OK)
    await _send_card(message, db_session, bot, await _reload(db_session, profile.id))


# ----------------------------- edit_age -----------------------------


@router.message(ProfileEditStates.edit_age, F.text)
async def on_edit_age(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(reg_texts.AGE_NOT_NUMBER)
        return
    age = int(text)
    settings_repo = SettingsRepository(db_session)
    min_age = (await settings_repo.get_int("min_age")) or _DEFAULT_MIN_AGE
    max_age = (await settings_repo.get_int("max_age")) or _DEFAULT_MAX_AGE
    if age < min_age:
        await message.answer(reg_texts.AGE_TOO_LOW.format(min_age=min_age))
        return
    if age > max_age:
        await message.answer(reg_texts.AGE_TOO_HIGH.format(max_age=max_age))
        return

    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        return
    await ProfileRepository(db_session).update(profile.id, age=age)
    await _log_edited(db_session, user.id, "age")
    await state.clear()
    await message.answer(texts.EDITED_OK)
    await _send_card(message, db_session, bot, await _reload(db_session, profile.id))


# ----------------------------- edit_gender (callback) -----------------------------


@router.callback_query(ProfileEditStates.edit_gender, GenderCb.filter())
async def on_edit_gender(
    callback: CallbackQuery,
    callback_data: GenderCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    gender = await DictionaryRepository(db_session).get_by_id(Gender, callback_data.gender_id)
    if gender is None or not gender.is_active:
        await callback.answer(reg_texts.GENDER_INVALID, show_alert=False)
        return
    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        await callback.answer()
        return
    await ProfileRepository(db_session).update(profile.id, gender_id=gender.id)
    await _log_edited(db_session, user.id, "gender_id")
    await state.clear()
    await callback.answer(texts.EDITED_OK)
    if callback.message is not None:
        await _send_card(callback.message, db_session, bot, await _reload(db_session, profile.id))


# ----------------------------- edit_la_min / edit_la_max -----------------------------


@router.message(ProfileEditStates.edit_la_min, F.text)
async def on_edit_la_min(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(reg_texts.AGE_NOT_NUMBER)
        return
    value = int(text)
    settings_repo = SettingsRepository(db_session)
    min_age = (await settings_repo.get_int("min_age")) or _DEFAULT_MIN_AGE
    max_age = (await settings_repo.get_int("max_age")) or _DEFAULT_MAX_AGE
    if value < min_age:
        await message.answer(reg_texts.AGE_TOO_LOW.format(min_age=min_age))
        return
    if value > max_age:
        await message.answer(reg_texts.AGE_TOO_HIGH.format(max_age=max_age))
        return
    await state.update_data(la_min=value)
    await message.answer(reg_texts.ASK_LOOKING_FOR_AGE_MAX)
    await state.set_state(ProfileEditStates.edit_la_max)


@router.message(ProfileEditStates.edit_la_max, F.text)
async def on_edit_la_max(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(reg_texts.AGE_NOT_NUMBER)
        return
    value = int(text)
    settings_repo = SettingsRepository(db_session)
    min_age = (await settings_repo.get_int("min_age")) or _DEFAULT_MIN_AGE
    max_age = (await settings_repo.get_int("max_age")) or _DEFAULT_MAX_AGE
    if value < min_age:
        await message.answer(reg_texts.AGE_TOO_LOW.format(min_age=min_age))
        return
    if value > max_age:
        await message.answer(reg_texts.AGE_TOO_HIGH.format(max_age=max_age))
        return

    data = await state.get_data()
    la_min = int(data.get("la_min", min_age))
    if value < la_min:
        await message.answer(reg_texts.AGE_MIN_GT_MAX)
        return

    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        return
    await ProfileRepository(db_session).update(
        profile.id,
        looking_for_age_min=la_min,
        looking_for_age_max=value,
    )
    await _log_edited(db_session, user.id, "looking_for_age_range")
    await state.clear()
    await message.answer(texts.EDITED_OK)
    await _send_card(message, db_session, bot, await _reload(db_session, profile.id))


# ----------------------------- edit_bio -----------------------------


@router.message(ProfileEditStates.edit_bio, F.text)
async def on_edit_bio(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(reg_texts.BIO_EMPTY)
        return
    settings_repo = SettingsRepository(db_session)
    max_len = (await settings_repo.get_int("bio_max_length")) or _DEFAULT_BIO_MAX
    if len(text) > max_len:
        await message.answer(reg_texts.BIO_TOO_LONG.format(max_len=max_len))
        return

    moderation = _moderation_service(db_session)
    result = await moderation.check_text(
        text,
        allow_links=False,
        target_kind="profile_bio",
        user_id=user.id,
    )
    if not result.approved:
        await message.answer(_moderation_error_text(result.reason))
        return

    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        return
    await ProfileRepository(db_session).update(profile.id, bio=text)
    await _log_edited(db_session, user.id, "bio")
    await state.clear()
    await message.answer(texts.EDITED_OK)
    await _send_card(message, db_session, bot, await _reload(db_session, profile.id))


# ----------------------------- edit_city -----------------------------


@router.message(ProfileEditStates.edit_city, F.text)
async def on_edit_city_text(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Текстовый ввод города при редактировании анкеты.

    Повторяет логику on_city_text из registration.py, но по завершении
    сохраняет в БД и показывает обновлённую карточку.
    """
    query = (message.text or "").strip()[:80]
    if not query:
        await message.answer(reg_texts.ASK_CITY)
        return

    geo = get_geo_service()
    result = geo.match_detailed(query)
    candidates = result.entries

    if not candidates:
        # Города нет в словаре — предлагаем сохранить как есть (см. registration).
        await state.update_data(city_freeform=query)
        kb = city_suggestions_kb(
            [],
            back_text=reg_texts.BTN_BACK_STEP,
            skip_text=reg_texts.BTN_CITY_ANY,
            keep_text=reg_texts.BTN_CITY_KEEP_TEMPLATE.format(city=query),
        )
        await message.answer(reg_texts.CITY_NO_MATCH_CAN_KEEP, reply_markup=kb)
        return

    if result.fuzzy:
        # Fuzzy-варианты не сохраняем молча («Ташкент» → «Тайшет»).
        await state.update_data(city_freeform=query)
        kb = city_suggestions_kb(
            candidates,
            back_text=reg_texts.BTN_BACK_STEP,
            skip_text=reg_texts.BTN_CITY_ANY,
            keep_text=reg_texts.BTN_CITY_KEEP_TEMPLATE.format(city=query),
        )
        await message.answer(reg_texts.CITY_FUZZY_SUGGESTIONS, reply_markup=kb)
        return

    if len(candidates) == 1:
        city_name = candidates[0].city
        await _save_city_and_render(message, state, db_session, bot, user.id, city_name)
        return

    norm_query = geo.normalize(query)
    for entry in candidates:
        if geo.normalize(entry.city) == norm_query:
            await _save_city_and_render(message, state, db_session, bot, user.id, entry.city)
            return

    kb = city_suggestions_kb(
        candidates,
        back_text=reg_texts.BTN_BACK_STEP,
        skip_text=reg_texts.BTN_CITY_ANY,
    )
    await message.answer(reg_texts.CITY_MULTIPLE_MATCHES, reply_markup=kb)


@router.callback_query(ProfileEditStates.edit_city, CityCb.filter())
async def on_edit_city_pick(
    callback: CallbackQuery,
    callback_data: CityCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Пользователь выбрал город из кнопок при редактировании."""
    await callback.answer()
    city_name: str | None = callback_data.city or None
    if callback.message is None:
        return
    await _save_city_and_render(callback.message, state, db_session, bot, user.id, city_name)


@router.callback_query(ProfileEditStates.edit_city, CityKeepCb.filter())
async def on_edit_city_keep(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """«Оставить как ввёл» при редактировании города."""
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    city_name = str(data.get("city_freeform") or "").strip()[:80]
    if not city_name:
        await callback.message.answer(reg_texts.ASK_CITY)
        return
    await _save_city_and_render(callback.message, state, db_session, bot, user.id, city_name)


@router.callback_query(ProfileEditStates.edit_city, RegBackCb.filter())
async def on_edit_city_back(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """«Назад» при редактировании города — отменяем редактирование."""
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await callback.message.answer(texts.EDIT_CANCELLED)


async def _save_city_and_render(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    bot: Bot,
    user_id: int,
    city: str | None,
) -> None:
    """Сохраняет город в профиль, логирует и показывает обновлённую карточку."""
    profile = await ProfileRepository(db_session).get_by_user_id(user_id)
    if profile is None:
        await state.clear()
        return
    await ProfileRepository(db_session).update(profile.id, city=city)
    await _log_edited(db_session, user_id, "city")
    await state.clear()
    if city:
        await message.answer(reg_texts.CITY_CONFIRMED.format(city=city))
    else:
        await message.answer(texts.EDITED_OK)
    await _send_card(message, db_session, bot, await _reload(db_session, profile.id))


# ----------------------- multi-select: fandoms / desired / interests / lfg ----------------------


async def _build_fandoms_kb(
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> InlineKeyboardMarkup:
    fandoms = await DictionaryRepository(db_session).list_active(Fandom)
    data = await state.get_data()
    selected = set(data.get("fandom_ids", []))
    kb = build_multi_select_kb(
        items=[(f.id, f.title) for f in fandoms],
        selected_ids=selected,
        page=page,
        entity="fandom",
        done_text=reg_texts.BTN_DONE,
        back_text=reg_texts.BTN_BACK_STEP,
    )
    await state.update_data(fandom_page=page)
    return kb


async def _send_fandoms_screen(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> None:
    kb = await _build_fandoms_kb(state, db_session, page=page)
    await message.answer(reg_texts.ASK_FANDOMS, reply_markup=kb)


async def _build_desired_fandoms_kb(
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> InlineKeyboardMarkup:
    fandoms = await DictionaryRepository(db_session).list_active(Fandom)
    data = await state.get_data()
    selected = set(data.get("desired_fandom_ids", []))
    kb = build_multi_select_kb(
        items=[(f.id, f.title) for f in fandoms],
        selected_ids=selected,
        page=page,
        entity="desired_fandom",
        done_text=reg_texts.BTN_DONE,
        back_text=reg_texts.BTN_BACK_STEP,
    )
    await state.update_data(desired_fandom_page=page)
    return kb


async def _send_desired_fandoms_screen(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> None:
    kb = await _build_desired_fandoms_kb(state, db_session, page=page)
    await message.answer(reg_texts.ASK_DESIRED_FANDOMS, reply_markup=kb)


async def _build_interests_kb(
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> InlineKeyboardMarkup:
    interests = await DictionaryRepository(db_session).list_active(Interest)
    data = await state.get_data()
    selected = set(data.get("interest_ids", []))
    kb = build_multi_select_kb(
        items=[(i.id, i.title) for i in interests],
        selected_ids=selected,
        page=page,
        entity="interest",
        done_text=reg_texts.BTN_DONE,
        back_text=reg_texts.BTN_BACK_STEP,
    )
    await state.update_data(interest_page=page)
    return kb


async def _send_interests_screen(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> None:
    kb = await _build_interests_kb(state, db_session, page=page)
    await message.answer(reg_texts.ASK_INTERESTS, reply_markup=kb)


async def _build_lfg_kb(
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> InlineKeyboardMarkup:
    genders = await DictionaryRepository(db_session).list_active(Gender)
    data = await state.get_data()
    selected = set(data.get("looking_for_gender_ids", []))
    kb = build_multi_select_kb(
        items=[(g.id, g.title) for g in genders],
        selected_ids=selected,
        page=page,
        entity="looking_for_gender",
        done_text=reg_texts.BTN_DONE,
        back_text=reg_texts.BTN_BACK_STEP,
    )
    await state.update_data(looking_for_gender_page=page)
    return kb


async def _send_lfg_screen(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> None:
    kb = await _build_lfg_kb(state, db_session, page=page)
    await message.answer(reg_texts.ASK_LOOKING_FOR_GENDERS, reply_markup=kb)


# `_refresh_multi_select_kb` извлечён в `app/bot/utils/multi_select.py`
# — переиспользуется в registration.py.


async def _handle_multi_select(
    *,
    callback: CallbackQuery,
    callback_data: MultiSelectCb,
    state: FSMContext,
    db_session: AsyncSession,
    state_key: str,
    page_key: str,
    require_non_empty: bool,
    empty_error: str,
    on_done,
    on_page,
    on_build_kb=None,
) -> None:
    """Подмножество multi-select dispatcher'а из registration.py: без back.

    Если передан `on_build_kb`, на toggle/page редактируем существующее
    сообщение (без миганий). Иначе fallback на старую логику delete + resend.
    """
    action = callback_data.action

    if action == "noop":
        await callback.answer()
        return

    if action == "back":
        # «Назад» в edit-режиме = отмена, сбрасываем state и не сохраняем.
        await callback.answer()
        await state.clear()
        return

    if action == "done":
        data = await state.get_data()
        selected = list(data.get(state_key, []))
        if require_non_empty and not selected:
            await callback.answer(empty_error, show_alert=True)
            return
        await callback.answer()
        await on_done(callback, state, db_session)
        return

    if action == "toggle":
        data = await state.get_data()
        selected = set(data.get(state_key, []))
        if callback_data.value in selected:
            selected.remove(callback_data.value)
        else:
            selected.add(callback_data.value)
        await state.update_data(**{state_key: list(selected)})
        page = int(data.get(page_key, 0))
        await callback.answer()
        await _refresh_multi_select_kb(
            callback,
            state,
            db_session,
            page=page,
            on_build_kb=on_build_kb,
            on_page=on_page,
        )
        return

    if action == "page":
        await callback.answer()
        await _refresh_multi_select_kb(
            callback,
            state,
            db_session,
            page=callback_data.value,
            on_build_kb=on_build_kb,
            on_page=on_page,
        )
        return

    await callback.answer()


@router.callback_query(ProfileEditStates.edit_fandoms, MultiSelectCb.filter())
async def on_edit_fandoms(
    callback: CallbackQuery,
    callback_data: MultiSelectCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if callback_data.entity != "fandom":
        await callback.answer()
        return

    async def _done(cb: CallbackQuery, st: FSMContext, sess: AsyncSession) -> None:
        await _save_multi_and_render(
            cb,
            st,
            sess,
            bot,
            user_id=user.id,
            state_key="fandom_ids",
            setter="set_fandoms",
            field_name="fandoms",
        )

    await _handle_multi_select(
        callback=callback,
        callback_data=callback_data,
        state=state,
        db_session=db_session,
        state_key="fandom_ids",
        page_key="fandom_page",
        require_non_empty=True,
        empty_error=reg_texts.FANDOMS_EMPTY,
        on_done=_done,
        on_page=_send_fandoms_screen,
        on_build_kb=_build_fandoms_kb,
    )


@router.callback_query(ProfileEditStates.edit_desired_fandoms, MultiSelectCb.filter())
async def on_edit_desired_fandoms(
    callback: CallbackQuery,
    callback_data: MultiSelectCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if callback_data.entity != "desired_fandom":
        await callback.answer()
        return

    async def _done(cb: CallbackQuery, st: FSMContext, sess: AsyncSession) -> None:
        await _save_multi_and_render(
            cb,
            st,
            sess,
            bot,
            user_id=user.id,
            state_key="desired_fandom_ids",
            setter="set_desired_fandoms",
            field_name="desired_fandoms",
        )

    await _handle_multi_select(
        callback=callback,
        callback_data=callback_data,
        state=state,
        db_session=db_session,
        state_key="desired_fandom_ids",
        page_key="desired_fandom_page",
        require_non_empty=True,
        empty_error=reg_texts.DESIRED_FANDOMS_EMPTY,
        on_done=_done,
        on_page=_send_desired_fandoms_screen,
        on_build_kb=_build_desired_fandoms_kb,
    )


@router.callback_query(ProfileEditStates.edit_interests, MultiSelectCb.filter())
async def on_edit_interests(
    callback: CallbackQuery,
    callback_data: MultiSelectCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if callback_data.entity != "interest":
        await callback.answer()
        return

    async def _done(cb: CallbackQuery, st: FSMContext, sess: AsyncSession) -> None:
        await _save_multi_and_render(
            cb,
            st,
            sess,
            bot,
            user_id=user.id,
            state_key="interest_ids",
            setter="set_interests",
            field_name="interests",
        )

    await _handle_multi_select(
        callback=callback,
        callback_data=callback_data,
        state=state,
        db_session=db_session,
        state_key="interest_ids",
        page_key="interest_page",
        require_non_empty=False,
        empty_error="",
        on_done=_done,
        on_page=_send_interests_screen,
        on_build_kb=_build_interests_kb,
    )


@router.callback_query(ProfileEditStates.edit_looking_for_genders, MultiSelectCb.filter())
async def on_edit_lfg(
    callback: CallbackQuery,
    callback_data: MultiSelectCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if callback_data.entity != "looking_for_gender":
        await callback.answer()
        return

    async def _done(cb: CallbackQuery, st: FSMContext, sess: AsyncSession) -> None:
        await _save_multi_and_render(
            cb,
            st,
            sess,
            bot,
            user_id=user.id,
            state_key="looking_for_gender_ids",
            setter="set_looking_for_genders",
            field_name="looking_for_genders",
        )

    await _handle_multi_select(
        callback=callback,
        callback_data=callback_data,
        state=state,
        db_session=db_session,
        state_key="looking_for_gender_ids",
        page_key="looking_for_gender_page",
        require_non_empty=True,
        empty_error=reg_texts.LOOKING_FOR_GENDERS_EMPTY,
        on_done=_done,
        on_page=_send_lfg_screen,
        on_build_kb=_build_lfg_kb,
    )


async def _save_multi_and_render(
    callback: CallbackQuery,
    state: FSMContext,
    db_session: AsyncSession,
    bot: Bot,
    *,
    user_id: int,
    state_key: str,
    setter: str,
    field_name: str,
) -> None:
    data = await state.get_data()
    ids = list(data.get(state_key, []))
    profile = await ProfileRepository(db_session).get_by_user_id(user_id)
    if profile is None:
        await state.clear()
        return
    await getattr(ProfileRepository(db_session), setter)(profile.id, ids)
    await _log_edited(db_session, user_id, field_name)
    await state.clear()
    msg = callback.message
    if msg is None:
        return
    await msg.answer(texts.EDITED_OK)
    await _send_card(msg, db_session, bot, await _reload(db_session, profile.id))


# ----------------------------- edit_own_vibe (callback picker) -----------------------------


@router.callback_query(ProfileEditStates.edit_own_vibe, VibePickCb.filter())
async def on_edit_vibe_pick_own(
    callback: CallbackQuery,
    callback_data: VibePickCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Пользователь выбрал свой вайб при редактировании (single-select)."""
    if callback_data.role != "own":
        await callback.answer()
        return

    vibes = await DictionaryRepository(db_session).list_active(Vibe)
    vibe = next((v for v in vibes if v.number == callback_data.number), None)
    if vibe is None:
        await callback.answer()
        return

    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        await callback.answer()
        return

    await ProfileRepository(db_session).update(profile.id, own_vibe_id=vibe.id)
    await ProfileRepository(db_session).set_vibes_need_review(profile.id, False)
    # Вайб выбран вручную — pending-заявка «Вайб по фото» (если была)
    # снимается с очереди модераторов.
    removed = await VibeByPhotoRepository(db_session).delete_pending_for_user(user.id)
    if removed:
        logger.info(
            "vbp: user {} picked vibe manually — {} pending request(s) removed",
            user.id,
            removed,
        )
    await _log_edited(db_session, user.id, "own_vibe_id")
    await state.clear()
    await callback.answer(texts.EDITED_OK)
    if callback.message is not None:
        await _send_card(callback.message, db_session, bot, await _reload(db_session, profile.id))


@router.callback_query(ProfileEditStates.edit_own_vibe, VibeByPhotoStartCb.filter())
async def cb_edit_vibe_by_photo_start(
    callback: CallbackQuery,
    callback_data: VibeByPhotoStartCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Запуск flow «Вайб по фото» из режима редактирования (Premium)."""
    if not has_premium_access(user):
        await callback.answer(vbp_texts.NOT_PREMIUM, show_alert=True)
        return
    await callback.answer()
    await state.update_data(
        vbp_photo_file_ids=[],
        vbp_origin="profile_edit",
    )
    await state.set_state(ProfileEditStates.vibe_by_photo_upload)
    if callback.message is not None:
        kb = vibe_by_photo_upload_kb(
            done_text=vbp_texts.BTN_VIBE_BY_PHOTO_DONE,
            cancel_text=vbp_texts.BTN_VIBE_BY_PHOTO_CANCEL,
            can_finish=False,
        )
        await callback.message.answer(vbp_texts.ASK_PHOTOS, reply_markup=kb)


@router.message(ProfileEditStates.vibe_by_photo_upload, F.photo)
async def on_edit_vibe_by_photo_photo(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Сбор фото (1-3) в режиме редактирования."""
    data = await state.get_data()
    file_ids: list[str] = list(data.get("vbp_photo_file_ids", []))
    if len(file_ids) >= 3:
        await message.answer(vbp_texts.PHOTO_MAX_REACHED)
        return
    if not message.photo:
        await message.answer(vbp_texts.WRONG_TYPE)
        return
    file_ids.append(message.photo[-1].file_id)
    await state.update_data(vbp_photo_file_ids=file_ids)
    received = len(file_ids)
    kb = vibe_by_photo_upload_kb(
        done_text=vbp_texts.BTN_VIBE_BY_PHOTO_DONE,
        cancel_text=vbp_texts.BTN_VIBE_BY_PHOTO_CANCEL,
        can_finish=received >= 1,
    )
    await message.answer(
        vbp_texts.PHOTO_RECEIVED_TEMPLATE.format(received=received), reply_markup=kb
    )


@router.message(ProfileEditStates.vibe_by_photo_upload, Command("done"))
async def cmd_edit_vibe_by_photo_done(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    await _profile_vbp_finalize(
        message=message, state=state, user=user, db_session=db_session, bot=bot
    )


@router.callback_query(ProfileEditStates.vibe_by_photo_upload, VibeByPhotoDoneCb.filter())
async def cb_edit_vibe_by_photo_done(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    msg = callback.message
    await callback.answer()
    if msg is None:
        return
    await _profile_vbp_finalize(message=msg, state=state, user=user, db_session=db_session, bot=bot)


@router.callback_query(ProfileEditStates.vibe_by_photo_upload, VibeByPhotoCancelCb.filter())
async def cb_edit_vibe_by_photo_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Отмена при редактировании — возвращаемся к обычному пикеру own_vibe."""
    await callback.answer()
    await state.update_data(vbp_photo_file_ids=[])
    msg = callback.message
    if msg is None:
        return
    if msg.bot is None:
        await state.clear()
        return
    show_vbp = has_premium_access(user)
    await msg.answer(vbp_texts.CANCELLED)
    await send_vibe_picker(
        msg.bot,
        msg.chat.id,
        db_session,
        role="own",
        page=0,
        show_vibe_by_photo=show_vbp,
        vibe_by_photo_origin="profile_edit",
    )
    await state.update_data(vbp_premium=show_vbp)
    await state.set_state(ProfileEditStates.edit_own_vibe)


@router.message(ProfileEditStates.vibe_by_photo_upload)
async def on_edit_vibe_by_photo_wrong_type(message: Message) -> None:
    await message.answer(vbp_texts.WRONG_TYPE)


async def _profile_vbp_finalize(
    *,
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Финализация Premium-фичи «Вайб по фото» в потоке profile_edit.

    Делегирует в общую функцию ``dispatch_vbp_request`` (та же, что
    используется из registration.py).
    """
    data = await state.get_data()
    file_ids: list[str] = list(data.get("vbp_photo_file_ids", []))
    if not file_ids:
        await message.answer(vbp_texts.PHOTO_NEED_AT_LEAST_ONE)
        return

    await dispatch_vbp_request(
        bot, db_session=db_session, user=user, file_ids=file_ids, origin="profile_edit"
    )

    await message.answer(vbp_texts.SENT_TO_MOD)
    await state.clear()


@router.callback_query(ProfileEditStates.edit_own_vibe, VibePageCb.filter())
async def on_edit_vibe_page_own(
    callback: CallbackQuery,
    callback_data: VibePageCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Навигация по страницам пикера own_vibe в режиме редактирования."""
    if callback_data.role != "own":
        await callback.answer()
        return
    await callback.answer()
    data = await state.get_data()
    show_vbp = bool(data.get("vbp_premium", False))
    if callback.message is not None:
        await edit_vibe_picker(
            callback.message,
            db_session,
            role="own",
            page=callback_data.page,
            show_vibe_by_photo=show_vbp,
            vibe_by_photo_origin="profile_edit",
        )


# ----------------------------- edit_desired_vibe (callback picker, multi) -------------------------


@router.callback_query(ProfileEditStates.edit_desired_vibe, VibePickCb.filter())
async def on_edit_vibe_pick_desired(
    callback: CallbackQuery,
    callback_data: VibePickCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Toggle номера вайба в FSM-наборе при редактировании desired_vibe."""
    if callback_data.role != "desired":
        await callback.answer()
        return

    data = await state.get_data()
    selected: set[int] = set(data.get("desired_vibe_numbers", []))
    n = callback_data.number
    if n in selected:
        selected.discard(n)
    else:
        selected.add(n)
    await state.update_data(desired_vibe_numbers=list(selected))
    await callback.answer()

    if callback.message is not None:
        await edit_vibe_picker(
            callback.message,
            db_session,
            role="desired",
            page=callback_data.page,
            selected_numbers=selected,
        )


@router.callback_query(ProfileEditStates.edit_desired_vibe, VibePageCb.filter())
async def on_edit_vibe_page_desired(
    callback: CallbackQuery,
    callback_data: VibePageCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Навигация по страницам пикера desired_vibe при редактировании."""
    if callback_data.role != "desired":
        await callback.answer()
        return
    data = await state.get_data()
    selected: set[int] = set(data.get("desired_vibe_numbers", []))
    await callback.answer()
    if callback.message is not None:
        await edit_vibe_picker(
            callback.message,
            db_session,
            role="desired",
            page=callback_data.page,
            selected_numbers=selected,
        )


@router.callback_query(ProfileEditStates.edit_desired_vibe, VibeDoneCb.filter())
async def on_edit_vibe_done_desired(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """«Готово» при редактировании desired_vibe — сохраняем выбор."""
    data = await state.get_data()
    selected_numbers: list[int] = list(data.get("desired_vibe_numbers", []))

    if not selected_numbers:
        await callback.answer(reg_texts.DESIRED_VIBE_NEED_NON_EMPTY, show_alert=True)
        return

    vibes = await DictionaryRepository(db_session).list_active(Vibe)
    number_to_id = {v.number: v.id for v in vibes}
    desired_vibe_ids = [number_to_id[n] for n in selected_numbers if n in number_to_id]

    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        await callback.answer()
        return

    await ProfileRepository(db_session).set_desired_vibe_ids(profile.id, desired_vibe_ids)
    await ProfileRepository(db_session).set_vibes_need_review(profile.id, False)
    await _log_edited(db_session, user.id, "desired_vibe_ids")
    await state.clear()
    await callback.answer(texts.EDITED_OK)
    if callback.message is not None:
        await _send_card(callback.message, db_session, bot, await _reload(db_session, profile.id))


@router.callback_query(ProfileEditStates.edit_desired_vibe, VibeAnyCb.filter())
async def on_edit_vibe_any_desired(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """«Любой вайб» при редактировании → очищаем desired_vibe_ids."""
    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        await callback.answer()
        return

    await ProfileRepository(db_session).set_desired_vibe_ids(profile.id, [])
    await ProfileRepository(db_session).set_vibes_need_review(profile.id, False)
    await _log_edited(db_session, user.id, "desired_vibe_ids")
    await state.clear()
    await callback.answer(texts.EDITED_OK)
    if callback.message is not None:
        await _send_card(callback.message, db_session, bot, await _reload(db_session, profile.id))


# ----------------------------- edit_media -----------------------------


@router.message(ProfileEditStates.edit_media, F.photo | F.video | F.animation)
async def on_edit_media(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if message.photo:
        media_type, file_id = "photo", message.photo[-1].file_id
    elif message.video is not None:
        media_type, file_id = "video", message.video.file_id
    elif message.animation is not None:
        media_type, file_id = "gif", message.animation.file_id
    else:
        await message.answer(reg_texts.MEDIA_WRONG_TYPE)
        return

    if photo_size_exceeded(message):
        await message.answer(reg_texts.MEDIA_TOO_LARGE)
        return

    pending_review = False
    if media_type in ("photo", "gif"):
        try:
            buf = BytesIO()
            await bot.download(file_id, destination=buf)
            image_bytes = buf.getvalue()
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to download user media on edit: {}", exc)
            await message.answer(reg_texts.PROFILE_SAVE_FAILED)
            return
        mod_service = ContentModerationService(ModerationRepository(db_session))
        result = await mod_service.check_image(
            image_bytes,
            target_kind="profile_media",
            user_id=user.id,
        )
        if result.decision == "rejected":
            await message.answer(reg_texts.MEDIA_REJECTED)
            return
        if result.decision == "manual_review":
            pending_review = True
    else:
        pending_review = True

    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        return
    await ProfileRepository(db_session).update(
        profile.id,
        main_media_type=media_type,
        main_media_file_id=file_id,
        is_pending_review=pending_review,
    )
    await _log_edited(db_session, user.id, "main_media")
    await state.clear()
    # Если медиа уходит на ручную модерацию (gif/video или photo в серой зоне
    # NSFW score) — анкета пропадает из выдачи до решения админа. Об этом нужно
    # явно предупредить, иначе пользователь не поймёт, почему его не находят.
    if pending_review:
        await message.answer(reg_texts.PROFILE_PENDING_REVIEW_OK)
        fresh = await _reload(db_session, profile.id)
        await notify_admins_profile_pending(
            bot,
            user_id=user.id,
            telegram_id=user.telegram_id,
            nickname=fresh.nickname,
            db_session=db_session,
        )
    else:
        await message.answer(texts.EDITED_OK)
    await _send_card(message, db_session, bot, await _reload(db_session, profile.id))


@router.message(ProfileEditStates.edit_media)
async def on_edit_media_wrong_type(message: Message) -> None:
    await message.answer(reg_texts.MEDIA_WRONG_TYPE)


# ----------------------------- waiting_music (Premium, Этап 8) -----------------------------


@router.message(ProfileEditStates.waiting_music, F.audio)
async def on_music_received(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if message.audio is None:
        await message.answer(pm_texts.MUSIC_WAITING_AUDIO)
        return
    file_id = message.audio.file_id
    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        return
    await ProfileRepository(db_session).set_music(profile.id, file_id)
    await state.clear()
    await message.answer(pm_texts.MUSIC_SAVED)
    await _send_card(message, db_session, bot, await _reload(db_session, profile.id))


@router.message(ProfileEditStates.waiting_music)
async def on_music_wrong_type(message: Message) -> None:
    """Любое не-аудио сообщение в состоянии ожидания музыки."""
    await message.answer(pm_texts.MUSIC_WAITING_AUDIO)


# ----------------------------- waiting_video_note (Premium, Этап 8) -----------------------------


@router.message(ProfileEditStates.waiting_video_note, F.video_note)
async def on_video_note_received(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if message.video_note is None:
        await message.answer(pm_texts.VIDEO_NOTE_WAITING)
        return
    file_id = message.video_note.file_id
    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None:
        await state.clear()
        return
    await ProfileRepository(db_session).set_video_note(profile.id, file_id)
    await state.clear()
    await message.answer(pm_texts.VIDEO_NOTE_SAVED)
    await _send_card(message, db_session, bot, await _reload(db_session, profile.id))


@router.message(ProfileEditStates.waiting_video_note, F.video)
async def on_video_note_got_video(message: Message) -> None:
    """Пользователь прислал обычное видео вместо кружка."""
    await message.answer(pm_texts.VIDEO_NOTE_WRONG_TYPE)


@router.message(ProfileEditStates.waiting_video_note)
async def on_video_note_wrong_type(message: Message) -> None:
    """Любое другое сообщение в состоянии ожидания кружка."""
    await message.answer(pm_texts.VIDEO_NOTE_WAITING)


# ----------------------------- DELETE flow -----------------------------


async def _do_delete_profile(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Удаляет анкету и все данные пользователя.

    Делегирует в `user_service.delete_user_data` (соц-данные → жалобы →
    профиль). Аккаунт и статус (Premium / модератор) сохраняются, бан не
    ставится — пользователь может сразу создать анкету заново.
    """
    await delete_user_data(user, db_session)

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            texts.PROFILE_DELETED_OK,
            reply_markup=main_menu_kb(is_registered=False),
        )


# ----------------------------- internals -----------------------------


async def _reload(db_session: AsyncSession, profile_id: int) -> Profile:
    """Перезагружает Profile из БД (после update делаем refresh)."""
    profile = await ProfileRepository(db_session).get_by_id(profile_id)
    if profile is None:
        raise LookupError(f"profile_id={profile_id} disappeared")
    await db_session.refresh(profile)
    return profile
