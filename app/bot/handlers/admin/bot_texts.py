"""Редактор текстов бота («✏️ Тексты»): карусель карточек по реестру bot_texts.

Тексты листаются один за другим (◀️/▶️, как пикер вайбов), под карточкой —
«✏️ Редактировать» (FSM-ввод), «↩️ Вернуть стандартный» и возврат в админ-меню.
Оверрайды лежат в app_settings (text_*). Для сообщений хранится
message.html_text (форматирование админа сохраняется, спецсимволы экранирует
aiogram), для кнопок — plain message.text.
"""

from __future__ import annotations

from html import escape as _html_escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import AdminMenuCb, AdminTextsCb, admin_back_home_kb
from app.bot.states.admin import AdminTextsStates
from app.db.models.user import User
from app.db.repositories.settings_repo import SettingsRepository
from app.services.bot_texts import GROUPS, placeholders_hint, validate_override
from app.texts import bot_texts_admin as texts
from app.texts.admin import ADMIN_MENU_BTN_HOME

router = Router(name="admin.bot_texts")


def _spec_at(group: str, idx: int):
    """Спека по позиции с нормализацией: кривой idx заворачивается по кругу."""
    specs = GROUPS[group]
    return specs[idx % len(specs)], idx % len(specs)


def _card_kb(group: str, idx: int, total: int, *, has_override: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if total > 1:
        b.button(
            text=texts.BTN_PREV_TEXT,
            callback_data=AdminTextsCb(action="open", group=group, idx=(idx - 1) % total),
        )
        b.button(text=f"{idx + 1}/{total}", callback_data=AdminTextsCb(action="noop"))
        b.button(
            text=texts.BTN_NEXT_TEXT,
            callback_data=AdminTextsCb(action="open", group=group, idx=(idx + 1) % total),
        )
    b.button(
        text=texts.BTN_EDIT_TEXT,
        callback_data=AdminTextsCb(action="edit", group=group, idx=idx),
    )
    if has_override:
        b.button(
            text=texts.BTN_RESET_TEXT,
            callback_data=AdminTextsCb(action="reset", group=group, idx=idx),
        )
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    if total > 1:
        b.adjust(3, 1, 1, 1)
    else:
        b.adjust(1)
    return b.as_markup()


def _card_text(group: str, idx: int, override: str | None) -> str:
    spec, idx = _spec_at(group, idx)
    if override:
        # Оверрайд сообщения — уже валидный HTML (html_text); кнопки — plain.
        current = _html_escape(override) if spec.is_button else override
        origin = texts.CARD_ORIGIN_OVERRIDE
    else:
        current = _html_escape(spec.default)
        origin = texts.CARD_ORIGIN_DEFAULT
    # Нативная цитата внутри оверрайда → внешний <blockquote> дал бы вложенность,
    # которую HTML-парсер Telegram отклоняет: показываем без обёртки.
    template = texts.TEXT_CARD_NOQUOTE if "<blockquote" in current else texts.TEXT_CARD
    return template.format(
        label=_html_escape(spec.label),
        pos=idx + 1,
        total=len(GROUPS[group]),
        current=current,
        hint=_html_escape(placeholders_hint(spec)),
        origin=origin,
    )


async def _render_card(
    message: Message, db_session: AsyncSession, group: str, idx: int, *, edit: bool = True
) -> None:
    spec, idx = _spec_at(group, idx)
    override = await SettingsRepository(db_session).get(spec.key)
    text = _card_text(group, idx, override)
    kb = _card_kb(group, idx, len(GROUPS[group]), has_override=bool(override))
    if edit:
        await show_screen(message, text=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(AdminTextsCb.filter(F.action == "noop"))
async def cb_texts_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(AdminTextsCb.filter(F.action == "open"))
async def cb_texts_open(
    callback: CallbackQuery,
    callback_data: AdminTextsCb,
    user: User,
    db_session: AsyncSession,
    state: FSMContext,
) -> None:
    if not is_admin(user) or callback_data.group not in GROUPS:
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await _render_card(callback.message, db_session, callback_data.group, callback_data.idx)


@router.callback_query(AdminTextsCb.filter(F.action == "edit"))
async def cb_texts_edit(
    callback: CallbackQuery,
    callback_data: AdminTextsCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user) or callback_data.group not in GROUPS:
        await callback.answer()
        return
    spec, idx = _spec_at(callback_data.group, callback_data.idx)
    await state.set_state(AdminTextsStates.ask_value)
    await state.update_data(text_group=callback_data.group, text_idx=idx)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            texts.ASK_NEW_TEXT.format(
                label=_html_escape(spec.label),
                max_len=spec.max_len,
                hint=_html_escape(placeholders_hint(spec)),
            ),
            reply_markup=admin_back_home_kb(),
        )


@router.callback_query(AdminTextsCb.filter(F.action == "reset"))
async def cb_texts_reset(
    callback: CallbackQuery,
    callback_data: AdminTextsCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user) or callback_data.group not in GROUPS:
        await callback.answer()
        return
    spec, idx = _spec_at(callback_data.group, callback_data.idx)
    await SettingsRepository(db_session).delete(spec.key)
    logger.info("admin {} reset bot text {}", user.id, spec.key)
    await callback.answer(texts.RESET_DONE)
    if callback.message:
        await _render_card(callback.message, db_session, callback_data.group, idx)


@router.message(StateFilter(AdminTextsStates.ask_value), F.text)
async def on_texts_new_value(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    group = data.get("text_group", "")
    if group not in GROUPS:
        await state.clear()
        return
    spec, idx = _spec_at(group, int(data.get("text_idx", 0)))

    value = (message.text or "") if spec.is_button else message.html_text
    error = validate_override(spec, value)
    if error is not None:
        await message.answer(error, reply_markup=admin_back_home_kb())
        return

    await SettingsRepository(db_session).set(spec.key, value, by_user_id=user.id)
    await state.clear()
    logger.info("admin {} set bot text {} ({} chars)", user.id, spec.key, len(value))
    await message.answer(texts.SAVED)
    await _render_card(message, db_session, group, idx, edit=False)
