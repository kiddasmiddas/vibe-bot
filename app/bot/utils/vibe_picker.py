"""Утилиты для отправки и обновления пикера вайбов (сетка 3×3 с пагинацией).

Используется в registration.py и profile.py для шагов own_vibe / desired_vibe.
Отделено в отдельный модуль, чтобы не дублировать логику send/edit.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputMediaPhoto, Message
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.registration import vibe_picker_kb
from app.db.models.dictionaries import Vibe
from app.texts import registration as texts

PAGE_SIZE = 9
TOTAL_VIBES = 36
TOTAL_PAGES = 4  # ceil(36 / 9) = 4


def numbers_for_page(page: int) -> list[int]:
    """Возвращает список номеров вайбов для страницы (0-based).

    page=0 → [1..9], page=1 → [10..18], page=2 → [19..27], page=3 → [28..36].
    """
    first = page * PAGE_SIZE + 1
    return list(range(first, first + PAGE_SIZE))


def page_for_number(number: int) -> int:
    """Возвращает номер страницы (0-based) для вайба с данным number."""
    return (number - 1) // PAGE_SIZE


async def fetch_page_image_file_id(db_session: AsyncSession, page: int) -> str | None:
    """Возвращает image_file_id вайба с минимальным number на странице (может быть None).

    Строки с префиксом ``placeholder:`` — реликт старого seed, когда колонка
    была NOT NULL. Telegram отвергает их как file_id (``Wrong string length``),
    поэтому трактуем как «картинки нет» — пикер уйдёт в text-only fallback.
    """
    first_number = page * PAGE_SIZE + 1
    stmt = select(Vibe.image_file_id).where(Vibe.number == first_number)
    result = await db_session.execute(stmt)
    row = result.scalar_one_or_none()
    if not isinstance(row, str) or row.startswith("placeholder:"):
        return None
    return row


async def send_vibe_picker(
    bot: Bot,
    chat_id: int,
    db_session: AsyncSession,
    *,
    role: str,
    page: int,
    selected_numbers: set[int] | None = None,
) -> Message:
    """Отправляет новое сообщение с пикером вайбов.

    Если у стартовой картинки страницы есть image_file_id — send_photo с caption.
    Если нет — send_message с текстом.
    Возвращает отправленное Message (нужно для последующего edit_vibe_picker).
    """
    image_file_id = await fetch_page_image_file_id(db_session, page)
    caption_text = texts.ASK_OWN_VIBE_PICKER if role == "own" else texts.ASK_DESIRED_VIBE_PICKER
    kb = vibe_picker_kb(
        role=role,
        page=page,
        total_pages=TOTAL_PAGES,
        page_size=PAGE_SIZE,
        selected_numbers=selected_numbers,
        done_text=texts.BTN_DONE,
        any_text=texts.BTN_DESIRED_VIBE_ANY,
    )

    if image_file_id:
        return await bot.send_photo(
            chat_id,
            photo=image_file_id,
            caption=caption_text,
            reply_markup=kb,
        )
    return await bot.send_message(chat_id, text=caption_text, reply_markup=kb)


async def edit_vibe_picker(
    callback_message: Message,
    db_session: AsyncSession,
    *,
    role: str,
    page: int,
    selected_numbers: set[int] | None = None,
) -> None:
    """Обновляет пикер вайбов in-place при навигации по страницам.

    Стратегия:
    - photo → photo: edit_media с InputMediaPhoto.
    - photo → text или text → photo: удалить + отправить новое (fallback).
    - text → text: edit_text.
    TelegramBadRequest при edit — логируем warning, не падаем.
    """
    new_image_file_id = await fetch_page_image_file_id(db_session, page)
    caption_text = texts.ASK_OWN_VIBE_PICKER if role == "own" else texts.ASK_DESIRED_VIBE_PICKER
    kb = vibe_picker_kb(
        role=role,
        page=page,
        total_pages=TOTAL_PAGES,
        page_size=PAGE_SIZE,
        selected_numbers=selected_numbers,
        done_text=texts.BTN_DONE,
        any_text=texts.BTN_DESIRED_VIBE_ANY,
    )

    has_photo = bool(callback_message.photo)

    if has_photo and new_image_file_id:
        # photo → photo: обновляем через edit_media.
        try:
            await callback_message.edit_media(
                media=InputMediaPhoto(media=new_image_file_id, caption=caption_text),
                reply_markup=kb,
            )
            return
        except TelegramBadRequest as exc:
            logger.warning(
                "edit_vibe_picker edit_media failed, falling back to delete+send: {}", exc
            )

    if has_photo != bool(new_image_file_id):
        # Тип сообщения меняется (photo→text или text→photo) — delete + send.
        try:
            await callback_message.delete()
        except TelegramBadRequest as exc:
            logger.warning("edit_vibe_picker: failed to delete message: {}", exc)

        chat_id = callback_message.chat.id
        bot = callback_message.bot
        if bot is None:
            return
        if new_image_file_id:
            await bot.send_photo(
                chat_id, photo=new_image_file_id, caption=caption_text, reply_markup=kb
            )
        else:
            await bot.send_message(chat_id, text=caption_text, reply_markup=kb)
        return

    # text → text.
    try:
        await callback_message.edit_text(text=caption_text, reply_markup=kb)
    except TelegramBadRequest as exc:
        logger.warning("edit_vibe_picker edit_text failed: {}", exc)
