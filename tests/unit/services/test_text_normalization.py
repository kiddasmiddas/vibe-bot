from __future__ import annotations

import pytest

from app.services.text_normalization import normalize_for_moderation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Привет", "привет"),
        ("П р и в е т", "привет"),  # spacing-trick (6 одиночных букв)
        ("Н@цизм", "нацизм"),  # leet
        ("hell​o", "hello"),  # zero-width space
        ("  hello   world  ", "hello world"),  # whitespace
        ("H3llo W0rld", "hello world"),  # leet
        ("", ""),  # edge: empty
        ("   ", ""),  # whitespace-only → empty after strip
    ],
)
def test_normalize_cases(raw: str, expected: str) -> None:
    assert normalize_for_moderation(raw) == expected


def test_normalize_does_not_collapse_short_normal_phrase() -> None:
    # Обычное предложение со словами длиной >1 НЕ должно схлапываться.
    assert normalize_for_moderation("я не он") == "я не он"


def test_normalize_strips_rtl_marks() -> None:
    # U+200E LEFT-TO-RIGHT MARK — категория Cf.
    assert normalize_for_moderation("a‎b") == "ab"


def test_normalize_nfkc_compatibility_forms() -> None:
    # Полноширинная латиница 'Ａ' = 'A' после NFKC.
    assert normalize_for_moderation("ＡＢＣ") == "abc"
