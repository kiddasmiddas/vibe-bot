"""Тесты навигации админки: на каждом экране есть возврат в /admin (Этап доработки).

1. Параметрический тест: каждая `*_kb` builder-функция содержит кнопку
   `AdminMenuCb(action="menu")` — защита от регресса «тупиков».
2. `admin_back_home_kb()` — ровно одна кнопка, она ведёт в главное меню.
3. `cb_back_to_menu` — сбрасывает FSM-state и отрисовывает меню.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.keyboards.admin import (
    AdminMenuCb,
    admin_back_home_kb,
    admin_cat_content_kb,
    admin_cat_moderation_kb,
    admin_cat_users_kb,
    admin_main_menu_kb,
    alley_duration_kb,
    alley_main_kb,
    alley_post_kb,
    analytics_kb,
    complaint_card_kb,
    complaint_list_kb,
    dict_item_kb,
    dicts_menu_kb,
    feed_admin_menu_kb,
    feed_post_actions_kb,
    premium_action_kb,
    premium_duration_kb,
    promo_segment_kb,
    review_menu_kb,
    review_post_kb,
    review_profile_card_kb,
    stopword_list_kb,
    user_action_kb,
    users_menu_kb,
)

# Каждая запись: (имя, готовая разметка). admin_main_menu_kb намеренно
# исключён — это корневой экран, точка возврата.
_KEYBOARDS_WITH_HOME = [
    ("users_menu_kb", users_menu_kb()),
    (
        "user_action_kb",
        user_action_kb(1, telegram_id=1, is_banned=False, is_hidden=False),
    ),
    ("complaint_list_kb", complaint_list_kb()),
    ("complaint_card_kb", complaint_card_kb(complaint_id=1, offset=0, status="new")),
    ("alley_main_kb", alley_main_kb()),
    ("alley_post_kb", alley_post_kb(1)),
    ("alley_duration_kb", alley_duration_kb("dur")),
    ("premium_action_kb", premium_action_kb(1, is_premium=True)),
    ("premium_duration_kb", premium_duration_kb(1)),
    ("promo_segment_kb", promo_segment_kb()),
    ("dicts_menu_kb", dicts_menu_kb()),
    ("dict_item_kb", dict_item_kb("fandom", 1, is_active=True)),
    ("review_menu_kb", review_menu_kb()),
    ("review_profile_card_kb", review_profile_card_kb(profile_id=1, offset=0)),
    ("review_post_kb", review_post_kb(1)),
    ("stopword_list_kb", stopword_list_kb(1)),
    ("feed_admin_menu_kb", feed_admin_menu_kb()),
    ("feed_post_actions_kb", feed_post_actions_kb(1, is_pending=True)),
    ("analytics_kb", analytics_kb()),
    ("admin_cat_moderation_kb", admin_cat_moderation_kb()),
    ("admin_cat_users_kb", admin_cat_users_kb()),
    ("admin_cat_content_kb", admin_cat_content_kb()),
]


def _callbacks(markup) -> list[str]:
    return [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]


@pytest.mark.parametrize(
    "name, markup",
    _KEYBOARDS_WITH_HOME,
    ids=[name for name, _ in _KEYBOARDS_WITH_HOME],
)
def test_admin_keyboard_has_return_to_menu(name: str, markup) -> None:
    """Каждый админский экран (кроме корневого) умеет вернуться в /admin."""
    menu_cb = AdminMenuCb(action="menu").pack()
    assert menu_cb in _callbacks(markup), f"{name}: нет кнопки возврата в главное меню /admin"


def test_admin_main_menu_kb_has_no_return_button() -> None:
    """Корневой экран /admin — точка возврата, кнопки «домой» у него быть не должно."""
    menu_cb = AdminMenuCb(action="menu").pack()
    assert menu_cb not in _callbacks(admin_main_menu_kb())


def test_admin_main_menu_is_five_categories() -> None:
    """Главное меню — ровно 5 категорий (минимализм вместо простыни кнопок)."""
    actions = [AdminMenuCb.unpack(cb).action for cb in _callbacks(admin_main_menu_kb())]
    assert actions == ["cat_moderation", "cat_users", "cat_content", "app_cfg", "analytics"]


def test_categories_cover_all_leaf_sections() -> None:
    """Каждый прежний раздел доступен из какой-то категории (ничего не потеряли)."""
    leaf_actions: set[str] = set()
    for kb in (admin_cat_moderation_kb(), admin_cat_users_kb(), admin_cat_content_kb()):
        for cb in _callbacks(kb):
            leaf_actions.add(AdminMenuCb.unpack(cb).action)
    # Разделы, которые должны быть достижимы через категории верхнего уровня.
    expected = {
        "complaints",
        "review",
        "vbp_queue",
        "stopwords",  # Модерация
        "users",
        "premium",  # Пользователи
        "feed",
        "alley",
        "ads",  # Контент
    }
    assert expected <= leaf_actions


def test_admin_back_home_kb_single_button() -> None:
    """admin_back_home_kb() — ровно одна кнопка, ведёт в главное меню."""
    markup = admin_back_home_kb()
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert len(buttons) == 1
    parsed = AdminMenuCb.unpack(buttons[0].callback_data)
    assert parsed.action == "menu"


@pytest.mark.asyncio
async def test_cb_back_to_menu_clears_state_and_renders_menu(monkeypatch) -> None:
    """cb_back_to_menu сбрасывает FSM-state и отрисовывает главное меню."""
    from app.bot.handlers.admin import menu as menu_module
    from app.db.models.user import User

    # Делаем пользователя админом.
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    user = User(telegram_id=111, username=None, is_banned=False, is_premium=False)
    user.id = 111

    callback = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()

    state = AsyncMock()

    await menu_module.cb_back_to_menu(callback, user, state)

    # FSM-state сброшен — иначе следующий ввод перехватит висящий промпт.
    state.clear.assert_awaited_once()
    # Меню отрисовано.
    callback.message.edit_text.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_cb_back_to_menu_falls_back_to_answer_on_media(monkeypatch) -> None:
    """Если edit_text падает (сообщение с медиа) — шлём новое сообщение."""
    from aiogram.exceptions import TelegramBadRequest

    from app.bot.handlers.admin import menu as menu_module
    from app.db.models.user import User

    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    user = User(telegram_id=111, username=None, is_banned=False, is_premium=False)
    user.id = 111

    callback = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock(
        side_effect=TelegramBadRequest(method=MagicMock(), message="no text in message")
    )
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()

    state = AsyncMock()

    await menu_module.cb_back_to_menu(callback, user, state)

    state.clear.assert_awaited_once()
    # edit_text упал — упали в answer.
    callback.message.answer.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_cb_back_to_menu_ignores_non_admin() -> None:
    """Не-админ не получает меню и FSM не трогается."""
    from app.bot.handlers.admin import menu as menu_module
    from app.db.models.user import User

    user = User(telegram_id=999, username=None, is_banned=False, is_premium=False)
    user.id = 999
    user.is_moderator = False

    callback = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()

    await menu_module.cb_back_to_menu(callback, user, state)

    callback.message.edit_text.assert_not_awaited()
    state.clear.assert_not_awaited()
    callback.answer.assert_awaited_once()
