"""Клавиатуры для FSM-регистрации."""

from __future__ import annotations

import random

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.dictionaries import Gender
from app.services.geo_service import CityEntry

# Пул животных-эмодзи для капчи. Целевое — всегда 🦊, три других — случайных.
_CAPTCHA_ANIMALS = ["🐱", "🐶", "🐰", "🐻", "🦝", "🐺", "🐸", "🦆", "🐼", "🐨"]
_CAPTCHA_TARGET = "🦊"

# Максимум кнопок-подсказок для автодополнения города (чтобы не перегружать клавиатуру).
_CITY_MAX_BUTTONS = 6


class GenderCb(CallbackData, prefix="gender_pick"):
    """Inline-callback одиночного выбора пола на шаге gender."""

    gender_id: int


class RegBackCb(CallbackData, prefix="reg_back"):
    """Кнопка «Назад» на шагах с текстовым вводом (gender/age и т.п.)."""

    step: str


class CaptchaCb(CallbackData, prefix="captcha"):
    """Callback кнопок антибот-капчи."""

    choice: str


class CityCb(CallbackData, prefix="city_pick"):
    """Выбор города из списка автодополнения."""

    city: str


class VibePickCb(CallbackData, prefix="vibe_pick"):
    """Кнопка с номером вайба в новом пикере.

    role: 'own' | 'desired' — какой шаг (single vs multi).
    page: текущая страница (0-based).
    number: номер вайба (1..36).
    """

    role: str
    page: int
    number: int


class VibePageCb(CallbackData, prefix="vibe_page"):
    """Стрелка ◀/▶ в пикере вайбов."""

    role: str  # 'own' | 'desired'
    page: int  # целевая страница


class VibeDoneCb(CallbackData, prefix="vibe_done"):
    """Кнопка «Готово» для desired_vibe multi-select."""

    pass


class VibeAnyCb(CallbackData, prefix="vibe_any"):
    """Кнопка «Любой вайб / Не важно» для desired_vibe."""

    pass


class VibeByPhotoStartCb(CallbackData, prefix="vbp_start"):
    """Кнопка «Вайб по фото» внутри пикера own_vibe (Premium-фича).

    origin: 'registration' | 'profile_edit' — откуда зашли, чтобы знать,
    куда возвращать пользователя после подбора.
    """

    origin: str


class VibeByPhotoDoneCb(CallbackData, prefix="vbp_done"):
    """Кнопка «Отправить» (или авто после 3 фото) в state vibe_by_photo_upload."""

    pass


class VibeByPhotoCancelCb(CallbackData, prefix="vbp_cancel"):
    """Кнопка «Отменить» — вернуть пользователя к обычному пикеру вайба."""

    pass


def build_captcha_kb() -> tuple[InlineKeyboardMarkup, str]:
    """Возвращает (клавиатуру, целевой эмодзи).

    Всегда создаёт свежий набор из 4 кнопок: целевое животное в случайной
    позиции + 3 случайных других из пула.
    """
    distractors = random.sample(_CAPTCHA_ANIMALS, 3)
    buttons = [*distractors, _CAPTCHA_TARGET]
    random.shuffle(buttons)

    builder = InlineKeyboardBuilder()
    for emoji in buttons:
        builder.button(text=emoji, callback_data=CaptchaCb(choice=emoji))
    builder.adjust(2)
    return builder.as_markup(), _CAPTCHA_TARGET


def gender_kb(genders: list[Gender]) -> InlineKeyboardMarkup:
    """Inline-клавиатура одиночного выбора пола, по 1 кнопке на ряд."""
    builder = InlineKeyboardBuilder()
    for gender in genders:
        builder.button(
            text=gender.title,
            callback_data=GenderCb(gender_id=gender.id),
        )
    builder.adjust(1)
    return builder.as_markup()


def city_suggestions_kb(
    candidates: list[CityEntry],
    *,
    back_text: str,
    skip_text: str,
) -> InlineKeyboardMarkup:
    """Клавиатура с кнопками-подсказками городов + «Назад» и «Не указывать».

    Ограничивает кол-во кнопок до ``_CITY_MAX_BUTTONS``, чтобы клавиатура
    оставалась читаемой.  Кнопки идут по 1 на ряд для удобства тапа.
    """
    builder = InlineKeyboardBuilder()
    for entry in candidates[:_CITY_MAX_BUTTONS]:
        label = entry.city if not entry.region else f"{entry.city} ({entry.region})"
        builder.button(text=label, callback_data=CityCb(city=entry.city))
    builder.button(text=skip_text, callback_data=CityCb(city=""))
    builder.button(text=back_text, callback_data=RegBackCb(step="city_back"))
    builder.adjust(1)
    return builder.as_markup()


def vibe_picker_kb(
    *,
    role: str,
    page: int,
    total_pages: int,
    page_size: int = 9,
    selected_numbers: set[int] | None = None,
    done_text: str,
    any_text: str,
    show_vibe_by_photo: bool = False,
    vibe_by_photo_text: str = "",
    vibe_by_photo_origin: str = "registration",
) -> InlineKeyboardMarkup:
    """Сетка 3×3 inline-кнопок выбора вайба с навигацией.

    Для single-режима (own): кнопки без галочек, нет «Готово»/«Любой».
    Для multi-режима (desired): галочки у выбранных, ряды «Готово» и «Любой вайб».
    Если ``show_vibe_by_photo`` — внизу добавляется кнопка «Вайб по фото»
    (Premium-фича). Кнопка отдаёт VibeByPhotoStartCb(origin=...).
    """
    is_multi = role == "desired"
    first_number = page * page_size + 1
    numbers = list(range(first_number, first_number + page_size))

    builder = InlineKeyboardBuilder()

    # 3×3 кнопки номеров.
    for n in numbers:
        if is_multi and selected_numbers and n in selected_numbers:
            label = f"✅ {n}"
        else:
            label = str(n)
        builder.button(
            text=label,
            callback_data=VibePickCb(role=role, page=page, number=n),
        )

    # Ряд навигации.
    nav_count = 0
    if page > 0:
        builder.button(
            text="◀",
            callback_data=VibePageCb(role=role, page=page - 1),
        )
        nav_count += 1
    # Центральная кнопка N/M — noop (переиспользуем VibePageCb с той же страницей,
    # но отображаем счётчик; чтобы не создавать лишний CB-класс, используем
    # VibePageCb с текущей страницей — хэндлер её просто проигнорирует/ответит пусто).
    builder.button(
        text=f"{page + 1}/{total_pages}",
        callback_data=VibePageCb(role=role, page=page),
    )
    nav_count += 1
    if page < total_pages - 1:
        builder.button(
            text="▶",
            callback_data=VibePageCb(role=role, page=page + 1),
        )
        nav_count += 1

    # Ряды действий (только для multi).
    rows: list[int] = [3, 3, 3, nav_count]
    if is_multi:
        builder.button(text=done_text, callback_data=VibeDoneCb())
        builder.button(text=any_text, callback_data=VibeAnyCb())
        rows += [1, 1]

    # Premium-фича «Вайб по фото» — отдельный ряд внизу. Видна только
    # Premium-юзерам и только в режиме одиночного выбора (own).
    if show_vibe_by_photo and role == "own" and vibe_by_photo_text:
        builder.button(
            text=vibe_by_photo_text,
            callback_data=VibeByPhotoStartCb(origin=vibe_by_photo_origin),
        )
        rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def vibe_by_photo_upload_kb(
    *,
    done_text: str,
    cancel_text: str,
    can_finish: bool,
) -> InlineKeyboardMarkup:
    """Клавиатура в состоянии vibe_by_photo_upload.

    Если ``can_finish=True`` (≥1 фото) — показываем кнопку «Отправить».
    «Отменить» доступна всегда — возвращает к обычному пикеру.
    """
    builder = InlineKeyboardBuilder()
    if can_finish:
        builder.button(text=done_text, callback_data=VibeByPhotoDoneCb())
    builder.button(text=cancel_text, callback_data=VibeByPhotoCancelCb())
    builder.adjust(1)
    return builder.as_markup()
