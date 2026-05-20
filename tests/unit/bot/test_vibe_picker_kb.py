"""Юнит-тесты для `app/bot/utils/vibe_picker` (числовые функции) и
`app/bot/keyboards/registration.vibe_picker_kb` (inline-клавиатура пикера).

Не требует БД — только чистая логика построения клавиатуры.
"""

from __future__ import annotations

from app.bot.keyboards.registration import (
    VibeAnyCb,
    VibeDoneCb,
    VibePageCb,
    VibePickCb,
    vibe_picker_kb,
)
from app.bot.utils.vibe_picker import numbers_for_page, page_for_number

# ---------------------------------------------------------------------------
# numbers_for_page
# ---------------------------------------------------------------------------


def test_numbers_for_page_0_returns_1_to_9() -> None:
    assert numbers_for_page(0) == list(range(1, 10))


def test_numbers_for_page_1_returns_10_to_18() -> None:
    assert numbers_for_page(1) == list(range(10, 19))


def test_numbers_for_page_2_returns_19_to_27() -> None:
    assert numbers_for_page(2) == list(range(19, 28))


def test_numbers_for_page_3_returns_28_to_36() -> None:
    assert numbers_for_page(3) == list(range(28, 37))


# ---------------------------------------------------------------------------
# page_for_number
# ---------------------------------------------------------------------------


def test_page_for_number_1_is_0() -> None:
    assert page_for_number(1) == 0


def test_page_for_number_9_is_0() -> None:
    assert page_for_number(9) == 0


def test_page_for_number_10_is_1() -> None:
    assert page_for_number(10) == 1


def test_page_for_number_18_is_1() -> None:
    assert page_for_number(18) == 1


def test_page_for_number_19_is_2() -> None:
    assert page_for_number(19) == 2


def test_page_for_number_27_is_2() -> None:
    assert page_for_number(27) == 2


def test_page_for_number_28_is_3() -> None:
    assert page_for_number(28) == 3


def test_page_for_number_36_is_3() -> None:
    assert page_for_number(36) == 3


# ---------------------------------------------------------------------------
# Helpers: extract flat button list from InlineKeyboardMarkup
# ---------------------------------------------------------------------------


def _flat_buttons(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


# ---------------------------------------------------------------------------
# vibe_picker_kb — own role (single-select, page 0, first page)
# ---------------------------------------------------------------------------


def test_vibe_picker_kb_own_page0_has_9_number_buttons() -> None:
    kb = vibe_picker_kb(
        role="own",
        page=0,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    pick_buttons = [
        btn for btn in _flat_buttons(kb) if btn.callback_data and "vibe_pick:" in btn.callback_data
    ]
    assert len(pick_buttons) == 9
    labels = [btn.text for btn in pick_buttons]
    for n in range(1, 10):
        assert str(n) in labels


def test_vibe_picker_kb_own_page0_no_checkmarks() -> None:
    kb = vibe_picker_kb(
        role="own",
        page=0,
        total_pages=4,
        page_size=9,
        selected_numbers={3, 5},  # own mode should ignore selection
        done_text="Готово",
        any_text="Любой вайб",
    )
    pick_buttons = [
        btn for btn in _flat_buttons(kb) if btn.callback_data and "vibe_pick:" in btn.callback_data
    ]
    for btn in pick_buttons:
        assert "✅" not in btn.text


def test_vibe_picker_kb_own_page0_no_done_button() -> None:
    kb = vibe_picker_kb(
        role="own",
        page=0,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    labels = [btn.text for btn in _flat_buttons(kb)]
    assert "Готово" not in labels


def test_vibe_picker_kb_own_page0_no_any_button() -> None:
    kb = vibe_picker_kb(
        role="own",
        page=0,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    labels = [btn.text for btn in _flat_buttons(kb)]
    assert "Любой вайб" not in labels


def test_vibe_picker_kb_own_page0_no_prev_arrow_has_next_arrow() -> None:
    kb = vibe_picker_kb(
        role="own",
        page=0,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    labels = [btn.text for btn in _flat_buttons(kb)]
    assert "◀" not in labels
    assert "▶" in labels


# ---------------------------------------------------------------------------
# vibe_picker_kb — desired role (multi-select, page 1, middle page)
# ---------------------------------------------------------------------------


def test_vibe_picker_kb_desired_page1_selected_numbers_have_checkmarks() -> None:
    kb = vibe_picker_kb(
        role="desired",
        page=1,
        total_pages=4,
        page_size=9,
        selected_numbers={10, 12},
        done_text="Готово",
        any_text="Любой вайб",
    )
    pick_buttons = [
        btn for btn in _flat_buttons(kb) if btn.callback_data and "vibe_pick:" in btn.callback_data
    ]
    label_10 = next(b.text for b in pick_buttons if "10" in b.text)
    label_12 = next(b.text for b in pick_buttons if "12" in b.text)
    assert label_10 == "✅ 10"
    assert label_12 == "✅ 12"


def test_vibe_picker_kb_desired_page1_unselected_no_checkmarks() -> None:
    kb = vibe_picker_kb(
        role="desired",
        page=1,
        total_pages=4,
        page_size=9,
        selected_numbers={10, 12},
        done_text="Готово",
        any_text="Любой вайб",
    )
    pick_buttons = [
        btn for btn in _flat_buttons(kb) if btn.callback_data and "vibe_pick:" in btn.callback_data
    ]
    for btn in pick_buttons:
        n = int(btn.text.replace("✅ ", ""))
        if n not in (10, 12):
            assert "✅" not in btn.text


def test_vibe_picker_kb_desired_page1_has_done_button() -> None:
    kb = vibe_picker_kb(
        role="desired",
        page=1,
        total_pages=4,
        page_size=9,
        selected_numbers={10},
        done_text="Готово",
        any_text="Любой вайб",
    )
    labels = [btn.text for btn in _flat_buttons(kb)]
    assert "Готово" in labels


def test_vibe_picker_kb_desired_page1_has_any_button() -> None:
    kb = vibe_picker_kb(
        role="desired",
        page=1,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    labels = [btn.text for btn in _flat_buttons(kb)]
    assert "Любой вайб" in labels


def test_vibe_picker_kb_desired_page1_has_both_arrows() -> None:
    kb = vibe_picker_kb(
        role="desired",
        page=1,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    labels = [btn.text for btn in _flat_buttons(kb)]
    assert "◀" in labels
    assert "▶" in labels


# ---------------------------------------------------------------------------
# vibe_picker_kb — callback data types are correct
# ---------------------------------------------------------------------------


def test_vibe_picker_kb_pick_callback_data_type() -> None:
    """Кнопки номеров несут VibePickCb, а не VibePageCb."""
    kb = vibe_picker_kb(
        role="own",
        page=0,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    pick_buttons = [
        btn for btn in _flat_buttons(kb) if btn.callback_data and "vibe_pick:" in btn.callback_data
    ]
    for btn in pick_buttons:
        parsed = VibePickCb.unpack(btn.callback_data)
        assert parsed.role == "own"
        assert 1 <= parsed.number <= 9
        assert parsed.page == 0


def test_vibe_picker_kb_done_callback_data_type() -> None:
    """Кнопка «Готово» несёт VibeDoneCb."""
    kb = vibe_picker_kb(
        role="desired",
        page=0,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    done_buttons = [btn for btn in _flat_buttons(kb) if btn.text == "Готово"]
    assert len(done_buttons) == 1
    VibeDoneCb.unpack(done_buttons[0].callback_data)  # must not raise


def test_vibe_picker_kb_any_callback_data_type() -> None:
    """Кнопка «Любой вайб» несёт VibeAnyCb."""
    kb = vibe_picker_kb(
        role="desired",
        page=0,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    any_buttons = [btn for btn in _flat_buttons(kb) if btn.text == "Любой вайб"]
    assert len(any_buttons) == 1
    VibeAnyCb.unpack(any_buttons[0].callback_data)  # must not raise


def test_vibe_picker_kb_next_arrow_callback_data_points_to_next_page() -> None:
    kb = vibe_picker_kb(
        role="own",
        page=0,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    next_btn = next(btn for btn in _flat_buttons(kb) if btn.text == "▶")
    parsed = VibePageCb.unpack(next_btn.callback_data)
    assert parsed.page == 1
    assert parsed.role == "own"


def test_vibe_picker_kb_prev_arrow_callback_data_points_to_prev_page() -> None:
    kb = vibe_picker_kb(
        role="desired",
        page=2,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    prev_btn = next(btn for btn in _flat_buttons(kb) if btn.text == "◀")
    parsed = VibePageCb.unpack(prev_btn.callback_data)
    assert parsed.page == 1
    assert parsed.role == "desired"


# ---------------------------------------------------------------------------
# vibe_picker_kb — last page has no next arrow
# ---------------------------------------------------------------------------


def test_vibe_picker_kb_last_page_no_next_arrow() -> None:
    kb = vibe_picker_kb(
        role="own",
        page=3,
        total_pages=4,
        page_size=9,
        selected_numbers=None,
        done_text="Готово",
        any_text="Любой вайб",
    )
    labels = [btn.text for btn in _flat_buttons(kb)]
    assert "▶" not in labels
    assert "◀" in labels
