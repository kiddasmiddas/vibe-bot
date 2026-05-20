from __future__ import annotations

from app.bot.utils.pagination import MultiSelectCb, build_multi_select_kb


def _make_items(n: int) -> list[tuple[int, str]]:
    return [(i, f"Item-{i}") for i in range(1, n + 1)]


def _flatten_texts(markup) -> list[str]:
    return [btn.text for row in markup.inline_keyboard for btn in row]


def test_page_0_of_three_has_next_no_prev() -> None:
    items = _make_items(20)
    markup = build_multi_select_kb(
        items=items,
        selected_ids=set(),
        page=0,
        entity="fandom",
        done_text="DONE",
        back_text="BACK",
    )
    texts = _flatten_texts(markup)
    # 8 toggle + nav (page indicator + next, no prev) + back + done.
    assert "Item-1" in texts and "Item-8" in texts
    assert "Item-9" not in texts
    assert "1/3" in texts
    assert "▶️" in texts
    assert "◀️" not in texts
    assert "DONE" in texts and "BACK" in texts


def test_last_page_has_prev_no_next() -> None:
    items = _make_items(20)
    markup = build_multi_select_kb(
        items=items,
        selected_ids=set(),
        page=2,
        entity="fandom",
        done_text="DONE",
        back_text="BACK",
    )
    texts = _flatten_texts(markup)
    assert "3/3" in texts
    assert "◀️" in texts
    assert "▶️" not in texts
    assert "Item-17" in texts and "Item-20" in texts


def test_selected_items_marked_with_checkmark() -> None:
    items = _make_items(10)
    markup = build_multi_select_kb(
        items=items,
        selected_ids={1, 5},
        page=0,
        entity="interest",
        done_text="DONE",
        back_text="BACK",
    )
    texts = _flatten_texts(markup)
    assert "✅ Item-1" in texts
    assert "✅ Item-5" in texts
    assert "Item-2" in texts  # без галочки


def test_single_page_has_no_navigation_row() -> None:
    items = _make_items(5)
    markup = build_multi_select_kb(
        items=items,
        selected_ids=set(),
        page=0,
        entity="interest",
        done_text="DONE",
        back_text="BACK",
    )
    texts = _flatten_texts(markup)
    assert "1/1" not in texts
    assert "◀️" not in texts and "▶️" not in texts
    assert "DONE" in texts


def test_callback_data_pack_unpack_roundtrip() -> None:
    cb = MultiSelectCb(action="toggle", entity="fandom", value=42)
    packed = cb.pack()
    parsed = MultiSelectCb.unpack(packed)
    assert parsed.action == "toggle"
    assert parsed.entity == "fandom"
    assert parsed.value == 42


def test_toggle_callback_data_on_kb_button() -> None:
    items = _make_items(3)
    markup = build_multi_select_kb(
        items=items,
        selected_ids=set(),
        page=0,
        entity="fandom",
        done_text="DONE",
        back_text="BACK",
    )
    # Первая кнопка — toggle для item id=1.
    first_btn = markup.inline_keyboard[0][0]
    cb = MultiSelectCb.unpack(first_btn.callback_data)
    assert cb.action == "toggle"
    assert cb.entity == "fandom"
    assert cb.value == 1


def test_back_and_done_each_on_own_row() -> None:
    """«Назад» и «Готово» должны быть в отдельных рядах (по 1 кнопке = вся ширина)."""
    items = _make_items(5)
    markup = build_multi_select_kb(
        items=items,
        selected_ids=set(),
        page=0,
        entity="interest",
        done_text="DONE",
        back_text="BACK",
    )
    rows = markup.inline_keyboard
    # Последний ряд — только «Готово».
    assert rows[-1] == [rows[-1][0]]
    assert rows[-1][0].text == "DONE"
    # Предпоследний ряд — только «Назад».
    assert rows[-2] == [rows[-2][0]]
    assert rows[-2][0].text == "BACK"
