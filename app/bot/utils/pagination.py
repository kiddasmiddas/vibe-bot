"""Универсальная утилита для постраничного inline-мультивыбора.

Используется на шагах регистрации (fandoms, desired_fandoms, interests,
looking_for_genders). Одна общая `CallbackData` `MultiSelectCb` с полем
`entity` различает контекст; хэндлер диспетчирует по `entity`.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

PAGE_SIZE = 8


class MultiSelectCb(CallbackData, prefix="msel"):
    """Унифицированный callback для multi-select экранов.

    - `action`: 'toggle' | 'page' | 'done' | 'back' | 'noop'
    - `entity`: 'fandom' | 'desired_fandom' | 'interest' | 'looking_for_gender'
    - `value`: id элемента (для toggle) или номер страницы (для page); 0 для done/back/noop.
    """

    action: str
    entity: str
    value: int


def _page_count(total: int, page_size: int) -> int:
    if total == 0:
        return 1
    return (total + page_size - 1) // page_size


def build_multi_select_kb(
    *,
    items: list[tuple[int, str]],
    selected_ids: set[int],
    page: int,
    entity: str,
    done_text: str,
    back_text: str,
    page_size: int = PAGE_SIZE,
) -> InlineKeyboardMarkup:
    """Собирает inline-клавиатуру multi-select экрана.

    Layout:
    - Сетка 2 кнопок на ряд (до 4 рядов = 8 элементов на странице).
      Выбранные элементы префиксированы галочкой ✅.
    - Ряд навигации «◀️ | N/M | ▶️» — только если страниц > 1.
    - Финальный ряд: [back_text] + [done_text].
    """
    builder = InlineKeyboardBuilder()

    total_pages = _page_count(len(items), page_size)
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = start + page_size
    page_items = items[start:end]

    for item_id, title in page_items:
        prefix = "✅ " if item_id in selected_ids else ""
        builder.button(
            text=f"{prefix}{title}",
            callback_data=MultiSelectCb(action="toggle", entity=entity, value=item_id),
        )

    n = len(page_items)
    rows: list[int] = [2] * (n // 2)
    if n % 2:
        rows.append(1)

    # Навигация (только если есть куда листать).
    if total_pages > 1:
        nav_buttons = 0
        if page > 0:
            builder.button(
                text="◀️",
                callback_data=MultiSelectCb(action="page", entity=entity, value=page - 1),
            )
            nav_buttons += 1
        builder.button(
            text=f"{page + 1}/{total_pages}",
            callback_data=MultiSelectCb(action="noop", entity=entity, value=0),
        )
        nav_buttons += 1
        if page < total_pages - 1:
            builder.button(
                text="▶️",
                callback_data=MultiSelectCb(action="page", entity=entity, value=page + 1),
            )
            nav_buttons += 1
        rows.append(nav_buttons)

    # «Назад» — отдельным рядом на всю ширину.
    builder.button(
        text=back_text,
        callback_data=MultiSelectCb(action="back", entity=entity, value=0),
    )
    rows.append(1)

    # «Готово» — отдельным рядом на всю ширину.
    builder.button(
        text=done_text,
        callback_data=MultiSelectCb(action="done", entity=entity, value=0),
    )
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()
