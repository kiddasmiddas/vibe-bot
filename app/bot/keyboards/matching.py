"""Inline-клавиатура с действиями над карточкой кандидата (этап 4.2)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.texts import matching as texts


class MatchingActionCb(CallbackData, prefix="match"):
    """Callback на действие в карточке кандидата.

    `action` ∈ {'like', 'superlike', 'dislike', 'skip', 'complain', 'block'}.
    `target_user_id` — `User.id` (внутренний PK), не Telegram ID.
    """

    action: str
    target_user_id: int


class SuperlikeCancelCb(CallbackData, prefix="slcancel"):
    """Callback кнопки «Отмена» под запросом текста для лайка с сообщением."""


class MatchingUndoCb(CallbackData, prefix="mt_undo"):
    """Callback кнопки «↩️ Назад» — возврат к предыдущей анкете (Premium).

    Stack глубины 1 — поддерживается только один шаг назад. Идентификатор
    предыдущего кандидата хранится в FSM, поэтому в callback_data ничего
    дополнительного передавать не нужно.
    """


class VibePendingCb(CallbackData, prefix="vibe_pend"):
    """Гард входа в поиск, пока модератор не подобрал вайб («Вайб по фото»).

    `action` ∈ {'back', 'pick_self'}:
    - back — вернуться в главное меню (подождать модератора);
    - pick_self — открыть пикер и выбрать вайб самостоятельно (pending-заявка
      модераторам при этом удаляется из очереди).
    """

    action: str


def vibe_pending_kb() -> InlineKeyboardMarkup:
    """Клавиатура гарда «вайб ещё не назначен»: подождать или выбрать самому."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_VIBE_PENDING_BACK, callback_data=VibePendingCb(action="back"))
    builder.button(
        text=texts.BTN_VIBE_PENDING_PICK_SELF,
        callback_data=VibePendingCb(action="pick_self"),
    )
    builder.adjust(1, 1)
    return builder.as_markup()


def superlike_cancel_kb() -> InlineKeyboardMarkup:
    """Клавиатура с одной кнопкой «Отмена» под запросом superlike-сообщения."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_CANCEL_SUPERLIKE, callback_data=SuperlikeCancelCb())
    return builder.as_markup()


def actions_kb(target_user_id: int, *, show_undo: bool = False) -> InlineKeyboardMarkup:
    """Inline-клавиатура действий над карточкой кандидата.

    Раскладка без `show_undo` — 2 + 1 + 3:
        [❤️ Лайк]   [👎 Дизлайк]
        [💬 С сообщением]
        [🚩 Жалоба] [🚫 Блок] [⏭]

    При `show_undo=True` (Premium-доступ И есть предыдущая анкета в стэке)
    под основными действиями добавляется отдельный ряд с одной кнопкой:
        [↩️ Назад]

    Free-юзеры этот ряд не видят — кнопка не рендерится. Это и UI-гейт,
    и страховка от подмены callback_data (хэндлер всё равно перепроверяет
    `has_premium_access`).
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_LIKE,
        callback_data=MatchingActionCb(action="like", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_DISLIKE,
        callback_data=MatchingActionCb(action="dislike", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_SUPERLIKE,
        callback_data=MatchingActionCb(action="superlike", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_COMPLAIN,
        callback_data=MatchingActionCb(action="complain", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_BLOCK,
        callback_data=MatchingActionCb(action="block", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_SKIP,
        callback_data=MatchingActionCb(action="skip", target_user_id=target_user_id),
    )
    if show_undo:
        builder.button(text=texts.BTN_UNDO, callback_data=MatchingUndoCb())
        builder.adjust(2, 1, 3, 1)
    else:
        builder.adjust(2, 1, 3)
    return builder.as_markup()


class AdSkipCb(CallbackData, prefix="ad_skip"):
    """Кнопка «Не интересно» под авто-рекламой — листаем анкеты дальше."""


def ad_kb(
    *,
    button_label: str | None,
    button_target: str | None,
    button_url: str | None,
) -> InlineKeyboardMarkup:
    """Клавиатура под авто-рекламой: опциональная кнопка перехода + «Не интересно».

    Кнопка перехода рендерится только если задан `button_label`:
    - `button_target='url'` → ссылка на спонсора (`button_url`);
    - `button_target='premium'` → открыть экран покупки Premium в боте.
    """
    from app.bot.keyboards.premium import PremiumActionCb
    from app.texts import ads_rotation as ad_texts

    builder = InlineKeyboardBuilder()
    if button_label:
        if button_target == "url" and button_url:
            builder.button(text=button_label, url=button_url)
        elif button_target == "premium":
            builder.button(text=button_label, callback_data=PremiumActionCb(action="open"))
    builder.button(text=ad_texts.BTN_NOT_INTERESTED, callback_data=AdSkipCb())
    builder.adjust(1)
    return builder.as_markup()
