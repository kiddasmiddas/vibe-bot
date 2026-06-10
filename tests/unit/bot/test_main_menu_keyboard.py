from __future__ import annotations

from app.bot.keyboards.main_menu import main_menu_kb
from app.texts import common as texts


def _flatten(markup) -> list[str]:
    return [btn.text for row in markup.keyboard for btn in row]


def test_main_menu_kb_registered_has_seven_buttons() -> None:
    markup = main_menu_kb(is_registered=True)
    buttons = _flatten(markup)

    assert buttons == [
        texts.BTN_MY_PROFILE,
        texts.BTN_SEARCH,
        texts.BTN_LIKES_MATCHES,
        texts.BTN_MINIAPP,
        texts.BTN_PREMIUM,
        texts.BTN_VIBE_BY_PHOTO_MENU,
        texts.BTN_SUPPORT,
    ]
    # Раскладка — три ряда по две кнопки + одиночный ряд «Поддержка».
    assert [len(row) for row in markup.keyboard] == [2, 2, 2, 1]
    assert markup.resize_keyboard is True


def test_main_menu_kb_anonymous_has_single_create_button() -> None:
    markup = main_menu_kb(is_registered=False)
    buttons = _flatten(markup)

    assert buttons == [texts.BTN_CREATE_PROFILE]
    assert markup.resize_keyboard is True
