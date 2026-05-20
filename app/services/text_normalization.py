"""Нормализация пользовательского текста для модерации.

 — порядок шагов
фиксирован. Любые изменения здесь должны сопровождаться обновлением
unit-тестов в `tests/unit/services/test_text_normalization.py`.
"""

from __future__ import annotations

import re
import unicodedata

# Leet-substitution: цифры и спец-символы → буквы.
_LEET_TABLE: dict[int, str] = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
        "@": "a",
        "$": "s",
    }
)

# Latin → Cyrillic lookalike folding. Стоп-листы в проекте — преимущественно
# русскоязычные, поэтому стягиваем латинские «двойники» в кириллицу. Это даёт
# нам устойчивость к тривиальной замене букв (например, после leet `@→a` между
# кириллическими буквами образуется латинская «a»).
_LATIN_TO_CYRILLIC: dict[int, str] = str.maketrans(
    {
        "a": "а",
        "e": "е",
        "o": "о",
        "p": "р",
        "c": "с",
        "y": "у",
        "x": "х",
        "k": "к",
        "b": "в",
        "h": "н",
        "m": "м",
        "t": "т",
    }
)


def _fold_latin_in_cyrillic_context(text: str) -> str:
    """Если в слове есть кириллица — переводим латинские «двойники» в кириллицу.

    Это сохраняет чисто-латинские слова ("hello") без изменений, но «лечит»
    смешанные строки вида "нaцизм" → "нацизм" (где 'a' — латинская).
    """
    result: list[str] = []
    for token in re.split(r"(\s+)", text):
        if token.isspace() or not token:
            result.append(token)
            continue
        has_cyrillic = any("а" <= ch <= "я" or ch == "ё" for ch in token)
        if has_cyrillic:
            result.append(token.translate(_LATIN_TO_CYRILLIC))
        else:
            result.append(token)
    return "".join(result)


# Regex для spacing-trick: ≥3 одиночных «словесных» символа, разделённых одним
# пробелом, плюс завершающий одиночный символ. Пример: "п р и в е т".
# Используем именно `\w` (без \s) — чтобы не схлопывать нормальные предложения
# с короткими словами ("я не он") мы НЕ требуем word-boundary в конце явно,
# но конструкция `(?:\b\w \b){3,}\w\b` уже подразумевает изолированные буквы.
_SPACING_TRICK_RE = re.compile(r"(?:\b\w\s){3,}\w\b", flags=re.UNICODE)

# Сжатие множественных пробелов.
_MULTI_SPACE_RE = re.compile(r"\s+")


def _strip_invisibles(text: str) -> str:
    """Удаляет символы категорий Cf (format) и Cc (control), кроме '\\n' и '\\t'."""
    result_chars: list[str] = []
    for ch in text:
        if ch in ("\n", "\t"):
            result_chars.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cf", "Cc"):
            continue
        result_chars.append(ch)
    return "".join(result_chars)


def _collapse_spacing_trick(text: str) -> str:
    """Схлопывает последовательности изолированных букв вида 'п р и в е т' → 'привет'.

    Срабатывает только если найдено ≥4 одиночных букв подряд (3 «буква+пробел»
    плюс одна замыкающая) — обычные короткие фразы вроде "я не он" не трогаются.
    """

    def _replace(match: re.Match[str]) -> str:
        return match.group(0).replace(" ", "")

    return _SPACING_TRICK_RE.sub(_replace, text)


def normalize_for_link_detection(raw: str) -> str:
    """Лёгкая нормализация — сохраняет `@`, `:`, `/`, цифры (нужны URL/mention).

    Шаги: NFKC + lowercase + strip invisibles. Без leet-подмены и
    Cyrillic-folding, чтобы не разрушать структуру ссылок и упоминаний.
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = text.lower()
    text = _strip_invisibles(text)
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def normalize_for_moderation(raw: str) -> str:
    """Готовит текст к матчингу со стоп-листом.

    Шаги:
      1. NFKC.
      2. lowercase.
      3. Удаление невидимых символов (Cf/Cc).
      4. Leet-substitution.
      5. Spacing-trick collapse.
      6. Сжатие пробелов + strip.
    """
    if not raw:
        return ""

    text = unicodedata.normalize("NFKC", raw)
    text = text.lower()
    text = _strip_invisibles(text)
    text = text.translate(_LEET_TABLE)
    text = _fold_latin_in_cyrillic_context(text)
    text = _collapse_spacing_trick(text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text
