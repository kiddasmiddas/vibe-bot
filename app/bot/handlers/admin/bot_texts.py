"""Редактор текстов бота («✏️ Тексты»): карусель карточек по реестру bot_texts.

Тексты листаются один за другим (◀️/▶️, как пикер вайбов). На карточке пуша,
у которого есть inline-кнопка, редактируются ОБА текста: само сообщение и текст
кнопки под ним (button_key в реестре) — двумя отдельными кнопками.

Оверрайды лежат в app_settings (text_*). Для сообщений хранится message.html_text
(форматирование админа сохраняется, спецсимволы экранирует aiogram), для кнопок
— plain message.text. Редактируемая цель адресуется КЛЮЧОМ (в FSM), возврат — к
карточке group/idx.
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
from app.services import bot_texts
from app.services.bot_texts import GROUPS, REGISTRY, placeholders_hint, validate_override
from app.texts import bot_texts_admin as texts
from app.texts.admin import ADMIN_MENU_BTN_HOME

router = Router(name="admin.bot_texts")


def _spec_at(group: str, idx: int):
    """Спека по позиции с нормализацией: кривой idx заворачивается по кругу."""
    specs = GROUPS[group]
    return specs[idx % len(specs)], idx % len(specs)


def _card_kb(
    group: str,
    idx: int,
    total: int,
    *,
    has_override: bool,
    button_key: str | None,
    button_has_override: bool,
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    nav = total > 1
    if nav:
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
        text=texts.BTN_EDIT_TEXT, callback_data=AdminTextsCb(action="edit", group=group, idx=idx)
    )
    if button_key is not None:
        b.button(
            text=texts.BTN_EDIT_BUTTON,
            callback_data=AdminTextsCb(action="edit_btn", group=group, idx=idx),
        )
    if has_override:
        b.button(
            text=texts.BTN_RESET_TEXT,
            callback_data=AdminTextsCb(action="reset", group=group, idx=idx),
        )
    if button_key is not None and button_has_override:
        b.button(
            text=texts.BTN_RESET_BUTTON,
            callback_data=AdminTextsCb(action="reset_btn", group=group, idx=idx),
        )
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    # Ряд навигации (◀ N/M ▶) — 3 в ряд, остальные кнопки по одной.
    # Лишние размеры в adjust игнорируются, поэтому 1-цы даём с запасом.
    if nav:
        b.adjust(3, 1, 1, 1, 1, 1)
    else:
        b.adjust(1)
    return b.as_markup()


def _card_text(group: str, idx: int, override: str | None, button_current: str | None) -> str:
    spec, idx = _spec_at(group, idx)
    if override:
        # Оверрайд сообщения — уже валидный HTML (html_text); кнопки — plain.
        current = _html_escape(override) if spec.is_button else override
        origin = texts.CARD_ORIGIN_OVERRIDE
    else:
        current = _html_escape(spec.default)
        origin = texts.CARD_ORIGIN_DEFAULT
    button_line = ""
    if button_current is not None:
        button_line = texts.CARD_BUTTON_LINE.format(button=_html_escape(button_current))
    # Нативная цитата внутри оверрайда → внешний <blockquote> дал бы вложенность,
    # которую HTML-парсер Telegram отклоняет: показываем без обёртки.
    template = texts.TEXT_CARD_NOQUOTE if "<blockquote" in current else texts.TEXT_CARD
    return template.format(
        label=_html_escape(spec.label),
        pos=idx + 1,
        total=len(GROUPS[group]),
        current=current,
        button_line=button_line,
        hint=_html_escape(placeholders_hint(spec)),
        origin=origin,
    )


async def _render_card(
    message: Message, db_session: AsyncSession, group: str, idx: int, *, edit: bool = True
) -> None:
    spec, idx = _spec_at(group, idx)
    repo = SettingsRepository(db_session)
    override = await repo.get(spec.key)
    button_current: str | None = None
    button_has_override = False
    if spec.button_key is not None:
        button_override = await repo.get(spec.button_key)
        button_has_override = bool(button_override)
        button_current = await bot_texts.get_text(repo, spec.button_key)
    text = _card_text(group, idx, override, button_current)
    kb = _card_kb(
        group,
        idx,
        len(GROUPS[group]),
        has_override=bool(override),
        button_key=spec.button_key,
        button_has_override=button_has_override,
    )
    if edit:
        await show_screen(message, text=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


def _target_key(group: str, idx: int, *, button: bool) -> str | None:
    """Ключ редактируемой цели: сам текст или связанная кнопка карточки."""
    spec, _ = _spec_at(group, idx)
    return spec.button_key if button else spec.key


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


@router.callback_query(AdminTextsCb.filter(F.action.in_({"edit", "edit_btn"})))
async def cb_texts_edit(
    callback: CallbackQuery,
    callback_data: AdminTextsCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user) or callback_data.group not in GROUPS:
        await callback.answer()
        return
    _, idx = _spec_at(callback_data.group, callback_data.idx)
    key = _target_key(callback_data.group, idx, button=callback_data.action == "edit_btn")
    if key is None:  # edit_btn на карточке без кнопки — стейл-нажатие
        await callback.answer()
        return
    target = REGISTRY[key]
    await state.set_state(AdminTextsStates.ask_value)
    await state.update_data(text_group=callback_data.group, text_idx=idx, text_key=key)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            texts.ASK_NEW_TEXT.format(
                label=_html_escape(target.label),
                max_len=target.max_len,
                hint=_html_escape(placeholders_hint(target)),
            ),
            reply_markup=admin_back_home_kb(),
        )


@router.callback_query(AdminTextsCb.filter(F.action.in_({"reset", "reset_btn"})))
async def cb_texts_reset(
    callback: CallbackQuery,
    callback_data: AdminTextsCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user) or callback_data.group not in GROUPS:
        await callback.answer()
        return
    _, idx = _spec_at(callback_data.group, callback_data.idx)
    key = _target_key(callback_data.group, idx, button=callback_data.action == "reset_btn")
    if key is None:
        await callback.answer()
        return
    await SettingsRepository(db_session).delete(key)
    logger.info("admin {} reset bot text {}", user.id, key)
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
    key = data.get("text_key", "")
    target = REGISTRY.get(key)
    if group not in GROUPS or target is None:
        await state.clear()
        return
    idx = int(data.get("text_idx", 0))

    value = (message.text or "") if target.is_button else message.html_text
    error = validate_override(target, value)
    if error is not None:
        await message.answer(error, reply_markup=admin_back_home_kb())
        return

    await SettingsRepository(db_session).set(key, value, by_user_id=user.id)
    await state.clear()
    logger.info("admin {} set bot text {} ({} chars)", user.id, key, len(value))
    await message.answer(texts.SAVED)
    await _render_card(message, db_session, group, idx, edit=False)
