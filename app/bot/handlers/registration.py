"""FSM-регистрация анкеты (этап 3.1, без вайбов и медиа).

10 шагов: nickname -> age -> gender -> looking_for_genders ->
looking_for_age_min -> looking_for_age_max -> bio -> fandoms ->
desired_fandoms -> interests.

На текущем этапе профиль НЕ создаётся в БД — все данные лежат в FSM
(Redis) до завершения этапа 3.3 (медиа). После 10-го шага бот показывает
заглушку про следующий этап.
"""

from __future__ import annotations

from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import main_menu_kb
from app.bot.keyboards.registration import (
    CaptchaCb,
    CityCb,
    GenderCb,
    RegBackCb,
    VibeAnyCb,
    VibeDoneCb,
    VibePageCb,
    VibePickCb,
    build_captcha_kb,
    city_suggestions_kb,
    gender_kb,
)
from app.bot.states.registration import RegistrationStates
from app.bot.utils.admin_notify import notify_admins_profile_pending
from app.bot.utils.media_limits import photo_size_exceeded
from app.bot.utils.pagination import MultiSelectCb, build_multi_select_kb
from app.bot.utils.render_profile import render_profile_card
from app.bot.utils.vibe_picker import (
    TOTAL_PAGES,
    edit_vibe_picker,
    send_vibe_picker,
)
from app.db.models.dictionaries import Fandom, Gender, Interest, Vibe
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.services.analytics_events import EventType
from app.services.content_moderation_service import ContentModerationService
from app.services.geo_service import get_geo_service
from app.texts import common as common_texts
from app.texts import registration as texts

router = Router(name="registration")

# Fallback-значения для настроек (на случай, если settings не заполнены).
_DEFAULT_NICKNAME_MIN = 2
_DEFAULT_NICKNAME_MAX = 32
_DEFAULT_MIN_AGE = 18
_DEFAULT_MAX_AGE = 80
_DEFAULT_BIO_MAX = 500


# ----------------------------- helpers -----------------------------


async def _settings(db_session: AsyncSession) -> SettingsRepository:
    return SettingsRepository(db_session)


def _moderation_service(db_session: AsyncSession) -> ContentModerationService:
    return ContentModerationService(ModerationRepository(db_session))


async def _moderation_error_text(reason: str | None) -> str:
    if reason == "link_detected":
        return texts.MODERATION_REJECTED_LINK
    return texts.MODERATION_REJECTED_STOP_WORD


async def _send_fandoms_screen(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> None:
    fandoms = await DictionaryRepository(db_session).list_active(Fandom)
    data = await state.get_data()
    selected = set(data.get("fandom_ids", []))
    kb = build_multi_select_kb(
        items=[(f.id, f.title) for f in fandoms],
        selected_ids=selected,
        page=page,
        entity="fandom",
        done_text=texts.BTN_DONE,
        back_text=texts.BTN_BACK_STEP,
    )
    await state.update_data(fandom_page=page)
    await message.answer(texts.ASK_FANDOMS, reply_markup=kb)


async def _send_desired_fandoms_screen(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> None:
    fandoms = await DictionaryRepository(db_session).list_active(Fandom)
    data = await state.get_data()
    selected = set(data.get("desired_fandom_ids", []))
    kb = build_multi_select_kb(
        items=[(f.id, f.title) for f in fandoms],
        selected_ids=selected,
        page=page,
        entity="desired_fandom",
        done_text=texts.BTN_DONE,
        back_text=texts.BTN_BACK_STEP,
    )
    await state.update_data(desired_fandom_page=page)
    await message.answer(texts.ASK_DESIRED_FANDOMS, reply_markup=kb)


async def _send_interests_screen(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> None:
    interests = await DictionaryRepository(db_session).list_active(Interest)
    data = await state.get_data()
    selected = set(data.get("interest_ids", []))
    kb = build_multi_select_kb(
        items=[(i.id, i.title) for i in interests],
        selected_ids=selected,
        page=page,
        entity="interest",
        done_text=texts.BTN_DONE,
        back_text=texts.BTN_BACK_STEP,
    )
    await state.update_data(interest_page=page)
    await message.answer(texts.ASK_INTERESTS, reply_markup=kb)


async def _send_looking_for_genders_screen(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    *,
    page: int = 0,
) -> None:
    genders = await DictionaryRepository(db_session).list_active(Gender)
    data = await state.get_data()
    selected = set(data.get("looking_for_gender_ids", []))
    kb = build_multi_select_kb(
        items=[(g.id, g.title) for g in genders],
        selected_ids=selected,
        page=page,
        entity="looking_for_gender",
        done_text=texts.BTN_DONE,
        back_text=texts.BTN_BACK_STEP,
    )
    await state.update_data(looking_for_gender_page=page)
    await message.answer(texts.ASK_LOOKING_FOR_GENDERS, reply_markup=kb)


async def _send_gender_screen(message: Message, db_session: AsyncSession) -> None:
    genders = await DictionaryRepository(db_session).list_active(Gender)
    await message.answer(texts.ASK_GENDER, reply_markup=gender_kb(genders))


# ----------------------------- entry / cancel -----------------------------


@router.message(F.text == common_texts.BTN_CREATE_PROFILE)
async def on_create_profile_entry(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    await state.clear()
    await AnalyticsRepository(db_session).log_event(
        user.id, event_type=EventType.REGISTRATION_START
    )
    kb, answer = build_captcha_kb()
    await state.update_data(captcha_answer=answer)
    await message.answer(texts.CAPTCHA_PROMPT.format(emoji=answer), reply_markup=kb)
    await state.set_state(RegistrationStates.captcha)


@router.message(
    StateFilter(
        RegistrationStates.captcha,
        RegistrationStates.nickname,
        RegistrationStates.age,
        RegistrationStates.gender,
        RegistrationStates.looking_for_genders,
        RegistrationStates.looking_for_age_min,
        RegistrationStates.looking_for_age_max,
        RegistrationStates.bio,
        RegistrationStates.city,
        RegistrationStates.fandoms,
        RegistrationStates.desired_fandoms,
        RegistrationStates.interests,
        RegistrationStates.own_vibe,
        RegistrationStates.desired_vibe,
        RegistrationStates.main_media,
    ),
    Command("cancel"),
)
async def cmd_cancel(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    await state.clear()
    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    is_registered = profile is not None and profile.is_completed
    await message.answer(
        texts.CANCELLED,
        reply_markup=main_menu_kb(is_registered=is_registered),
    )


# ----------------------------- captcha -----------------------------


@router.callback_query(StateFilter(RegistrationStates.captcha), CaptchaCb.filter())
async def on_captcha_choice(
    callback: CallbackQuery,
    callback_data: CaptchaCb,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    correct = data.get("captcha_answer", "")
    if callback_data.choice == correct:
        await callback.answer()
        await state.update_data(captcha_answer=None)
        if callback.message is not None:
            await callback.message.answer(texts.ASK_NICKNAME)
        await state.set_state(RegistrationStates.nickname)
    else:
        await callback.answer()
        kb, new_answer = build_captcha_kb()
        await state.update_data(captcha_answer=new_answer)
        if callback.message is not None:
            await callback.message.answer(texts.CAPTCHA_WRONG)
            await callback.message.answer(
                texts.CAPTCHA_PROMPT.format(emoji=new_answer), reply_markup=kb
            )


# ----------------------------- 1. nickname -----------------------------


@router.message(StateFilter(RegistrationStates.nickname), F.text)
async def on_nickname(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    text = (message.text or "").strip()
    settings_repo = await _settings(db_session)
    min_len = (await settings_repo.get_int("nickname_min_length")) or _DEFAULT_NICKNAME_MIN
    max_len = (await settings_repo.get_int("nickname_max_length")) or _DEFAULT_NICKNAME_MAX

    if len(text) < min_len:
        await message.answer(texts.NICKNAME_TOO_SHORT.format(min_len=min_len))
        return
    if len(text) > max_len:
        await message.answer(texts.NICKNAME_TOO_LONG.format(max_len=max_len))
        return

    moderation = _moderation_service(db_session)
    result = await moderation.check_text(
        text,
        allow_links=False,
        target_kind="profile_nickname",
        user_id=user.id,
    )
    if not result.approved:
        await message.answer(await _moderation_error_text(result.reason))
        return

    await state.update_data(nickname=text)
    await message.answer(texts.ASK_AGE)
    await state.set_state(RegistrationStates.age)


# ----------------------------- 2. age -----------------------------


@router.message(StateFilter(RegistrationStates.age), F.text)
async def on_age(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(texts.AGE_NOT_NUMBER)
        return
    age = int(text)
    settings_repo = await _settings(db_session)
    min_age = (await settings_repo.get_int("min_age")) or _DEFAULT_MIN_AGE
    max_age = (await settings_repo.get_int("max_age")) or _DEFAULT_MAX_AGE

    if age < min_age:
        await message.answer(texts.AGE_TOO_LOW.format(min_age=min_age))
        return
    if age > max_age:
        await message.answer(texts.AGE_TOO_HIGH.format(max_age=max_age))
        return

    await state.update_data(age=age)
    await _send_gender_screen(message, db_session)
    await state.set_state(RegistrationStates.gender)


# ----------------------------- 3. gender -----------------------------


@router.callback_query(StateFilter(RegistrationStates.gender), GenderCb.filter())
async def on_gender_pick(
    callback: CallbackQuery,
    callback_data: GenderCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    gender = await DictionaryRepository(db_session).get_by_id(Gender, callback_data.gender_id)
    if gender is None or not gender.is_active:
        await callback.answer(texts.GENDER_INVALID, show_alert=False)
        return
    await state.update_data(gender_id=gender.id)
    await callback.answer()
    if callback.message is not None:
        await _send_looking_for_genders_screen(callback.message, state, db_session)
    await state.set_state(RegistrationStates.looking_for_genders)


# ----------------------------- 4. looking_for_genders (multi-select) -----------------------------


@router.callback_query(StateFilter(RegistrationStates.looking_for_genders), MultiSelectCb.filter())
async def on_looking_for_genders(
    callback: CallbackQuery,
    callback_data: MultiSelectCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    if callback_data.entity != "looking_for_gender":
        await callback.answer()
        return
    await _handle_multi_select(
        callback=callback,
        callback_data=callback_data,
        state=state,
        db_session=db_session,
        state_key="looking_for_gender_ids",
        page_key="looking_for_gender_page",
        require_non_empty=True,
        empty_error=texts.LOOKING_FOR_GENDERS_EMPTY,
        on_done=_after_looking_for_genders_done,
        on_back=_back_to_gender,
        on_page=_send_looking_for_genders_screen,
    )


async def _after_looking_for_genders_done(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    if callback.message is not None:
        await callback.message.answer(texts.ASK_LOOKING_FOR_AGE_MIN)
    await state.set_state(RegistrationStates.looking_for_age_min)


async def _back_to_gender(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    if callback.message is not None:
        await _send_gender_screen(callback.message, db_session)
    await state.set_state(RegistrationStates.gender)


# ----------------------------- 5. looking_for_age_min -----------------------------


@router.message(StateFilter(RegistrationStates.looking_for_age_min), F.text)
async def on_looking_for_age_min(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(texts.AGE_NOT_NUMBER)
        return
    value = int(text)
    settings_repo = await _settings(db_session)
    min_age = (await settings_repo.get_int("min_age")) or _DEFAULT_MIN_AGE
    max_age = (await settings_repo.get_int("max_age")) or _DEFAULT_MAX_AGE

    if value < min_age:
        await message.answer(texts.AGE_TOO_LOW.format(min_age=min_age))
        return
    if value > max_age:
        await message.answer(texts.AGE_TOO_HIGH.format(max_age=max_age))
        return

    await state.update_data(la_min=value)
    await message.answer(texts.ASK_LOOKING_FOR_AGE_MAX)
    await state.set_state(RegistrationStates.looking_for_age_max)


# ----------------------------- 6. looking_for_age_max -----------------------------


@router.message(StateFilter(RegistrationStates.looking_for_age_max), F.text)
async def on_looking_for_age_max(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(texts.AGE_NOT_NUMBER)
        return
    value = int(text)
    settings_repo = await _settings(db_session)
    min_age = (await settings_repo.get_int("min_age")) or _DEFAULT_MIN_AGE
    max_age = (await settings_repo.get_int("max_age")) or _DEFAULT_MAX_AGE

    if value < min_age:
        await message.answer(texts.AGE_TOO_LOW.format(min_age=min_age))
        return
    if value > max_age:
        await message.answer(texts.AGE_TOO_HIGH.format(max_age=max_age))
        return

    data = await state.get_data()
    la_min = int(data.get("la_min", min_age))
    if value < la_min:
        await message.answer(texts.AGE_MIN_GT_MAX)
        return

    await state.update_data(la_max=value)
    await message.answer(texts.ASK_BIO)
    await state.set_state(RegistrationStates.bio)


# ----------------------------- 7. bio -----------------------------


@router.message(StateFilter(RegistrationStates.bio), F.text)
async def on_bio(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(texts.BIO_EMPTY)
        return
    settings_repo = await _settings(db_session)
    max_len = (await settings_repo.get_int("bio_max_length")) or _DEFAULT_BIO_MAX
    if len(text) > max_len:
        await message.answer(texts.BIO_TOO_LONG.format(max_len=max_len))
        return

    moderation = _moderation_service(db_session)
    result = await moderation.check_text(
        text,
        allow_links=False,
        target_kind="profile_bio",
        user_id=user.id,
    )
    if not result.approved:
        await message.answer(await _moderation_error_text(result.reason))
        return

    await state.update_data(bio=text)
    await _send_city_prompt(message)
    await state.set_state(RegistrationStates.city)


# ----------------------------- 8. city -----------------------------


async def _send_city_prompt(message: Message) -> None:
    """Отправляет приглашение ввести город без клавиатуры."""
    await message.answer(texts.ASK_CITY)


@router.message(StateFilter(RegistrationStates.city), F.text)
async def on_city_text(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Пользователь вводит название города текстом.

    Стратегия:
    - 0 совпадений → сообщить, предложить ввести ещё раз (без кнопок).
    - 1 совпадение (точное или единственный вариант) → сохранить сразу.
    - 2–N совпадений → показать кнопки-подсказки.
    """
    query = (message.text or "").strip()
    if not query:
        await message.answer(texts.ASK_CITY)
        return

    geo = get_geo_service()
    candidates = geo.match(query)

    if not candidates:
        await message.answer(
            texts.CITY_NO_MATCH_NO_SUGGESTIONS,
        )
        return

    # Единственное совпадение — принимаем без лишних кнопок.
    if len(candidates) == 1:
        city_name = candidates[0].city
        await state.update_data(city=city_name)
        await message.answer(texts.CITY_CONFIRMED.format(city=city_name))
        await _send_fandoms_screen(message, state, db_session)
        await state.set_state(RegistrationStates.fandoms)
        return

    # Точное совпадение в наборе → тоже принимаем сразу.
    norm_query = geo.normalize(query)
    for entry in candidates:
        if geo.normalize(entry.city) == norm_query:
            city_name = entry.city
            await state.update_data(city=city_name)
            await message.answer(texts.CITY_CONFIRMED.format(city=city_name))
            await _send_fandoms_screen(message, state, db_session)
            await state.set_state(RegistrationStates.fandoms)
            return

    # Несколько вариантов → кнопки.
    kb = city_suggestions_kb(
        candidates,
        back_text=texts.BTN_BACK_STEP,
        skip_text=texts.BTN_CITY_ANY,
    )
    await message.answer(texts.CITY_MULTIPLE_MATCHES, reply_markup=kb)


@router.callback_query(StateFilter(RegistrationStates.city), CityCb.filter())
async def on_city_pick(
    callback: CallbackQuery,
    callback_data: CityCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Пользователь нажал кнопку-подсказку города (или «Не указывать»).

    Пустая строка `city=""` означает «не указывать» — сохраняем None.
    """
    await callback.answer()
    city_name: str | None = callback_data.city or None
    if callback.message is None:
        return

    if city_name:
        await state.update_data(city=city_name)
        await callback.message.answer(texts.CITY_CONFIRMED.format(city=city_name))
    else:
        await state.update_data(city=None)

    await _send_fandoms_screen(callback.message, state, db_session)
    await state.set_state(RegistrationStates.fandoms)


@router.callback_query(StateFilter(RegistrationStates.city), RegBackCb.filter())
async def on_city_back(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Кнопка «Назад» на шаге city → возвращаемся к bio."""
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(texts.ASK_BIO)
    await state.set_state(RegistrationStates.bio)


# ----------------------------- 9. fandoms (multi-select) -----------------------------


@router.callback_query(StateFilter(RegistrationStates.fandoms), MultiSelectCb.filter())
async def on_fandoms(
    callback: CallbackQuery,
    callback_data: MultiSelectCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    if callback_data.entity != "fandom":
        await callback.answer()
        return
    await _handle_multi_select(
        callback=callback,
        callback_data=callback_data,
        state=state,
        db_session=db_session,
        state_key="fandom_ids",
        page_key="fandom_page",
        require_non_empty=True,
        empty_error=texts.FANDOMS_EMPTY,
        on_done=_after_fandoms_done,
        on_back=_back_to_city,
        on_page=_send_fandoms_screen,
    )


async def _after_fandoms_done(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    if callback.message is not None:
        await _send_desired_fandoms_screen(callback.message, state, db_session)
    await state.set_state(RegistrationStates.desired_fandoms)


async def _back_to_city(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    """«Назад» из шага fandoms → возврат на шаг city."""
    if callback.message is not None:
        await callback.message.answer(texts.ASK_CITY)
    await state.set_state(RegistrationStates.city)


# ----------------------------- 10. desired_fandoms -----------------------------


@router.callback_query(StateFilter(RegistrationStates.desired_fandoms), MultiSelectCb.filter())
async def on_desired_fandoms(
    callback: CallbackQuery,
    callback_data: MultiSelectCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    if callback_data.entity != "desired_fandom":
        await callback.answer()
        return
    await _handle_multi_select(
        callback=callback,
        callback_data=callback_data,
        state=state,
        db_session=db_session,
        state_key="desired_fandom_ids",
        page_key="desired_fandom_page",
        require_non_empty=True,
        empty_error=texts.DESIRED_FANDOMS_EMPTY,
        on_done=_after_desired_fandoms_done,
        on_back=_back_to_fandoms,
        on_page=_send_desired_fandoms_screen,
    )


async def _after_desired_fandoms_done(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    if callback.message is not None:
        await _send_interests_screen(callback.message, state, db_session)
    await state.set_state(RegistrationStates.interests)


async def _back_to_fandoms(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    if callback.message is not None:
        await _send_fandoms_screen(callback.message, state, db_session)
    await state.set_state(RegistrationStates.fandoms)


# ----------------------------- 11. interests -----------------------------


@router.callback_query(StateFilter(RegistrationStates.interests), MultiSelectCb.filter())
async def on_interests(
    callback: CallbackQuery,
    callback_data: MultiSelectCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    if callback_data.entity != "interest":
        await callback.answer()
        return
    await _handle_multi_select(
        callback=callback,
        callback_data=callback_data,
        state=state,
        db_session=db_session,
        state_key="interest_ids",
        page_key="interest_page",
        require_non_empty=False,  # интересы можно пропустить пустыми
        empty_error="",
        on_done=_after_interests_done,
        on_back=_back_to_desired_fandoms,
        on_page=_send_interests_screen,
    )


async def _after_interests_done(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    # Этап 3.2: переходим в выбор собственного вайба.
    message = callback.message
    if message is None:
        return
    await _enter_own_vibe_step(message, state, db_session)


async def _enter_own_vibe_step(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Загружает активные вайбы и переводит FSM в шаг own_vibe.

    Если вайбов нет — сообщает и сбрасывает FSM, чтобы пользователь не
    застрял (см. DoD: бот не падает на edge-case пустого справочника).
    """
    vibes = await DictionaryRepository(db_session).list_active(Vibe)
    if not vibes:
        logger.error("No active vibes in DB — registration cannot proceed")
        await message.answer(texts.VIBE_LIST_EMPTY)
        await state.clear()
        return

    bot = message.bot
    if bot is None:
        return
    await send_vibe_picker(bot, message.chat.id, db_session, role="own", page=0)
    await state.update_data(own_vibe_page=0)
    await state.set_state(RegistrationStates.own_vibe)


# ----------------------------- 12. own_vibe (callback picker) -----------------------------


@router.callback_query(StateFilter(RegistrationStates.own_vibe), VibePickCb.filter())
async def on_vibe_pick_own(
    callback: CallbackQuery,
    callback_data: VibePickCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Пользователь нажал кнопку с номером вайба (own, single-select)."""
    if callback_data.role != "own":
        await callback.answer()
        return

    vibes = await DictionaryRepository(db_session).list_active(Vibe)
    vibe = next((v for v in vibes if v.number == callback_data.number), None)
    if vibe is None:
        await callback.answer()
        return

    await callback.answer()
    await state.update_data(own_vibe_id=vibe.id, desired_vibe_numbers=[], desired_vibe_page=0)

    # Переходим к desired_vibe: новое сообщение (новый шаг).
    bot = callback.bot
    msg = callback.message
    if bot is None or msg is None:
        return
    # Удаляем сообщение с пикером own_vibe (опционально, не падаем при ошибке).
    try:
        await msg.delete()
    except TelegramAPIError:
        pass

    await send_vibe_picker(
        bot, msg.chat.id, db_session, role="desired", page=0, selected_numbers=set()
    )
    await state.set_state(RegistrationStates.desired_vibe)


@router.callback_query(StateFilter(RegistrationStates.own_vibe), VibePageCb.filter())
async def on_vibe_page_own(
    callback: CallbackQuery,
    callback_data: VibePageCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Навигация по страницам пикера own_vibe."""
    if callback_data.role != "own":
        await callback.answer()
        return
    # Центральная noop-кнопка (целевая страница == текущей).
    data = await state.get_data()
    current_page = int(data.get("own_vibe_page", 0))
    if callback_data.page == current_page:
        await callback.answer()
        return

    await callback.answer()
    await state.update_data(own_vibe_page=callback_data.page)
    if callback.message is not None:
        await edit_vibe_picker(callback.message, db_session, role="own", page=callback_data.page)


# ----------------------------- 13. desired_vibe (callback picker, multi) --------------------------


@router.callback_query(StateFilter(RegistrationStates.desired_vibe), VibePickCb.filter())
async def on_vibe_pick_desired(
    callback: CallbackQuery,
    callback_data: VibePickCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Toggle номера вайба в FSM-наборе desired_vibe_numbers."""
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


@router.callback_query(StateFilter(RegistrationStates.desired_vibe), VibePageCb.filter())
async def on_vibe_page_desired(
    callback: CallbackQuery,
    callback_data: VibePageCb,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Навигация по страницам пикера desired_vibe."""
    if callback_data.role != "desired":
        await callback.answer()
        return

    data = await state.get_data()
    # Центральная noop-кнопка: определяем по тому, что page совпадает с кнопками текущего экрана.
    # page в VibePageCb — целевая страница; для центральной кнопки она == текущей.
    # Мы не храним desired_vibe_page явно — определяем из callback_data кнопок сетки на экране.
    # Для надёжности просто редактируем на новую страницу (даже если та же).
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


@router.callback_query(StateFilter(RegistrationStates.desired_vibe), VibeDoneCb.filter())
async def on_vibe_done_desired(
    callback: CallbackQuery,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """«Готово» — завершаем выбор desired_vibe и переходим к main_media."""
    data = await state.get_data()
    selected_numbers: list[int] = list(data.get("desired_vibe_numbers", []))

    if not selected_numbers:
        await callback.answer(texts.DESIRED_VIBE_NEED_NON_EMPTY, show_alert=True)
        return

    # Конвертируем номера в IDs.
    vibes = await DictionaryRepository(db_session).list_active(Vibe)
    number_to_id = {v.number: v.id for v in vibes}
    desired_vibe_ids = [number_to_id[n] for n in selected_numbers if n in number_to_id]

    await state.update_data(desired_vibe_ids=desired_vibe_ids)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(texts.ASK_MEDIA)
    await state.set_state(RegistrationStates.main_media)


@router.callback_query(StateFilter(RegistrationStates.desired_vibe), VibeAnyCb.filter())
async def on_vibe_any_desired(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """«Любой вайб / Не важно» — очищаем desired_vibe_ids и переходим к main_media."""
    await state.update_data(desired_vibe_ids=[])
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(texts.ASK_MEDIA)
    await state.set_state(RegistrationStates.main_media)


async def _back_to_desired_fandoms(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    if callback.message is not None:
        await _send_desired_fandoms_screen(callback.message, state, db_session)
    await state.set_state(RegistrationStates.desired_fandoms)


# ----------------------------- 14. main_media -----------------------------


@router.message(
    StateFilter(RegistrationStates.main_media),
    F.photo | F.video | F.animation,
)
async def on_main_media(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Принимает фото / видео / GIF, прогоняет через NSFW и финализирует анкету.

    Поведение модерации ():
      - photo / gif: качаем байты, прогоняем через ContentModerationService.check_image.
        rejected → просим переслать другое (state сохраняется).
        manual_review → сохраняем профиль с is_pending_review=True.
        approved → сохраняем как обычно.
      - video: всегда manual_review (NudeNet видео не умеет), is_pending_review=True.
    """
    media_type, file_id = _extract_media(message)
    if media_type is None or file_id is None:
        # Не должно случиться при текущих фильтрах, но защищаемся от рассинхрона.
        await message.answer(texts.MEDIA_WRONG_TYPE)
        return

    if photo_size_exceeded(message):
        await message.answer(texts.MEDIA_TOO_LARGE)
        return

    pending_review = False

    if media_type in ("photo", "gif"):
        try:
            buf = BytesIO()
            await bot.download(file_id, destination=buf)
            image_bytes = buf.getvalue()
        except Exception as exc:  # pragma: no cover — сетевые ошибки
            logger.exception("Failed to download user media: {}", exc)
            await message.answer(texts.PROFILE_SAVE_FAILED)
            return

        mod_service = ContentModerationService(ModerationRepository(db_session))
        result = await mod_service.check_image(
            image_bytes,
            target_kind="profile_media",
            user_id=user.id,
        )
        if result.decision == "rejected":
            await message.answer(texts.MEDIA_REJECTED)
            return
        if result.decision == "manual_review":
            pending_review = True
    else:
        # video — на ручную модерацию всегда ().
        pending_review = True

    await state.update_data(
        main_media_type=media_type,
        main_media_file_id=file_id,
        pending_review=pending_review,
    )

    await _finalize_registration(message, state, user, db_session, bot)


@router.message(StateFilter(RegistrationStates.main_media))
async def on_main_media_wrong_type(message: Message) -> None:
    """Любое сообщение в media-шаге, не являющееся фото/видео/GIF."""
    await message.answer(texts.MEDIA_WRONG_TYPE)


def _extract_media(message: Message) -> tuple[str | None, str | None]:
    if message.photo:
        # Берём самое большое разрешение.
        return "photo", message.photo[-1].file_id
    if message.video is not None:
        return "video", message.video.file_id
    if message.animation is not None:
        return "gif", message.animation.file_id
    return None, None


async def _finalize_registration(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Создаёт Profile + M2M-связи, шлёт превью карточки и главное меню.

    При ошибке SQLAlchemy логируем `logger.exception`, шлём PROFILE_SAVE_FAILED
    и оставляем FSM-data + состояние на main_media: пользователь может
    повторить присылкой нового медиа (см. DoD промпта 3.3).
    """
    data = await state.get_data()

    profile_repo = ProfileRepository(db_session)
    dictionary_repo = DictionaryRepository(db_session)
    analytics_repo = AnalyticsRepository(db_session)

    try:
        profile = await profile_repo.create(
            user_id=user.id,
            nickname=data["nickname"],
            age=data["age"],
            gender_id=data["gender_id"],
            looking_for_age_min=data["la_min"],
            looking_for_age_max=data["la_max"],
            bio=data["bio"],
            city=data.get("city"),
            own_vibe_id=data["own_vibe_id"],
            main_media_type=data["main_media_type"],
            main_media_file_id=data["main_media_file_id"],
            is_pending_review=bool(data.get("pending_review", False)),
        )

        await profile_repo.set_fandoms(profile.id, list(data.get("fandom_ids", [])))
        await profile_repo.set_desired_fandoms(profile.id, list(data.get("desired_fandom_ids", [])))
        await profile_repo.set_interests(profile.id, list(data.get("interest_ids", [])))
        await profile_repo.set_looking_for_genders(
            profile.id, list(data.get("looking_for_gender_ids", []))
        )
        await profile_repo.set_desired_vibe_ids(profile.id, list(data.get("desired_vibe_ids", [])))
        await profile_repo.mark_completed(profile.id)
        await db_session.refresh(profile)
    except SQLAlchemyError as exc:
        logger.exception("Failed to save profile for user_id={}: {}", user.id, exc)
        try:
            await db_session.rollback()
        except SQLAlchemyError:  # pragma: no cover — не критично, главное — UX
            pass
        await message.answer(texts.PROFILE_SAVE_FAILED)
        return

    await analytics_repo.log_event(user.id, event_type=EventType.PROFILE_COMPLETED)

    # Подгружаем справочники для рендера карточки.
    gender = await dictionary_repo.get_by_id(Gender, profile.gender_id)
    own_vibe = await dictionary_repo.get_by_id(Vibe, profile.own_vibe_id)

    all_vibes = await dictionary_repo.list_active(Vibe)
    desired_vibe_ids_set = set(data.get("desired_vibe_ids", []))
    desired_vibes = [v for v in all_vibes if v.id in desired_vibe_ids_set]

    all_fandoms = await dictionary_repo.list_active(Fandom)
    all_interests = await dictionary_repo.list_active(Interest)
    all_genders = await dictionary_repo.list_active(Gender)

    fandom_ids = set(data.get("fandom_ids", []))
    desired_fandom_ids = set(data.get("desired_fandom_ids", []))
    interest_ids = set(data.get("interest_ids", []))
    looking_for_gender_ids = set(data.get("looking_for_gender_ids", []))

    fandoms = [f for f in all_fandoms if f.id in fandom_ids]
    desired_fandoms = [f for f in all_fandoms if f.id in desired_fandom_ids]
    interests = [i for i in all_interests if i.id in interest_ids]
    looking_for_genders = [g for g in all_genders if g.id in looking_for_gender_ids]

    # Только gender и own_vibe обязательны.
    if gender is None or own_vibe is None:
        # Справочник внезапно опустел между шагами — крайне маловероятно, но
        # не позволяем UX-падению: отдаём что есть текстом без карточки.
        logger.error(
            "Missing dictionary entries on finalize for user_id={}: gender={} own_vibe={}",
            user.id,
            profile.gender_id,
            profile.own_vibe_id,
        )
        await state.clear()
        await message.answer(
            texts.PROFILE_CREATED_OK,
            reply_markup=main_menu_kb(is_registered=True),
        )
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

    await state.clear()

    await message.answer(texts.RENDER_HEADER_OK)
    caption = rendered.text
    chat_id = message.chat.id
    try:
        if rendered.media_type == "photo":
            await bot.send_photo(chat_id, rendered.media_file_id, caption=caption)
        elif rendered.media_type == "video":
            await bot.send_video(chat_id, rendered.media_file_id, caption=caption)
        elif rendered.media_type == "gif":
            await bot.send_animation(chat_id, rendered.media_file_id, caption=caption)
        else:
            await message.answer(caption)
    except Exception as exc:  # pragma: no cover — медиа не критично к UX финала
        logger.warning("Failed to send profile preview media: {}", exc)
        await message.answer(caption)

    final_text = (
        texts.PROFILE_PENDING_REVIEW_OK if profile.is_pending_review else texts.PROFILE_CREATED_OK
    )
    await message.answer(final_text, reply_markup=main_menu_kb(is_registered=True))

    # Анкета ушла на ручную модерацию медиа — уведомляем админов, чтобы они
    # могли оперативно одобрить её через /admin → «На проверке».
    if profile.is_pending_review:
        await notify_admins_profile_pending(
            bot,
            user_id=user.id,
            telegram_id=user.telegram_id,
            nickname=profile.nickname,
        )


# ----------------------------- multi-select dispatcher -----------------------------


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
    on_back,
    on_page,
) -> None:
    """Общая логика toggle/page/done/back для multi-select экранов.

    Хранение выбранных id в FSM — list[int] (Redis JSON-friendly), на время
    операций конвертируется в set для быстрых проверок присутствия.
    """
    action = callback_data.action

    if action == "noop":
        await callback.answer()
        return

    if action == "back":
        await callback.answer()
        await on_back(callback, state, db_session)
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
        # Перерисовываем тот же экран с новой галочкой.
        if callback.message is not None:
            try:
                await callback.message.delete()
            except TelegramAPIError:
                pass
            await on_page(callback.message, state, db_session, page=page)
        return

    if action == "page":
        await callback.answer()
        if callback.message is not None:
            try:
                await callback.message.delete()
            except TelegramAPIError:
                pass
            await on_page(callback.message, state, db_session, page=callback_data.value)
        return

    await callback.answer()


__all__ = [
    "TOTAL_PAGES",
    "router",
]
