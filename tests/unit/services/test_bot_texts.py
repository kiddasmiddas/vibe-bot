"""Юнит-тесты фреймворка редактируемых текстов (app/services/bot_texts.py).

Реестр, валидация оверрайдов от админа, чтение с fallback и safe-format:
кривой шаблон никогда не роняет отправку — уходит дефолт из кода.
"""

from __future__ import annotations

import pytest

from app.services import bot_texts
from app.services.bot_texts import (
    GROUPS,
    REGISTRY,
    extract_placeholders,
    get_text,
    render_text,
    validate_override,
)


class _StubSettings:
    def __init__(self, values: dict[str, str] | None = None, *, fail: bool = False) -> None:
        self._values = values or {}
        self._fail = fail

    async def get(self, key: str) -> str | None:
        if self._fail:
            raise ConnectionError("db down")
        return self._values.get(key)


# --------------------------- реестр ---------------------------


def test_registry_consistent() -> None:
    """Ключи уникальны, дефолты содержат ровно объявленные плейсхолдеры."""
    all_specs = [s for group in GROUPS.values() for s in group]
    assert len(all_specs) == len(REGISTRY)
    for spec in all_specs:
        assert extract_placeholders(spec.default) == set(spec.placeholders)


def test_buttons_marked_and_short() -> None:
    for key in (bot_texts.KEY_BTN_VIEW_LIKES, bot_texts.KEY_BTN_OPEN_POST):
        spec = REGISTRY[key]
        assert spec.is_button is True
        assert spec.max_len == bot_texts.MAX_LEN_BUTTON


# --------------------------- extract_placeholders ---------------------------


def test_extract_placeholders_variants() -> None:
    assert extract_placeholders("без подстановок") == set()
    assert extract_placeholders("лайков: {n}") == {"n"}
    assert extract_placeholders("{{литеральные}} скобки") == set()
    # Битые скобки → None.
    assert extract_placeholders("оборванная {") is None
    # Позиционный `{}` и доступ к атрибутам не совпадут с allowed-списком.
    assert extract_placeholders("{}") == {""}
    assert extract_placeholders("{n.__class__}") == {"n.__class__"}


# --------------------------- validate_override ---------------------------


def test_validate_rejects_empty_and_long() -> None:
    spec = REGISTRY[bot_texts.KEY_LIKE_PUSH_ONE]
    assert validate_override(spec, "   ") is not None
    assert validate_override(spec, "x" * (spec.max_len + 1)) is not None
    assert validate_override(spec, "Новый текст лайка") is None


def test_validate_rejects_unknown_placeholder() -> None:
    spec = REGISTRY[bot_texts.KEY_LIKE_PUSH_MANY]  # допустим только {n}
    assert validate_override(spec, "Лайков: {n}") is None
    assert validate_override(spec, "Лайков: {count}") is not None
    # Формат-инъекция через атрибуты тоже отбивается.
    assert validate_override(spec, "{n.__class__}") is not None


def test_validate_rejects_broken_braces() -> None:
    spec = REGISTRY[bot_texts.KEY_WELCOME]
    assert validate_override(spec, "Привет {") is not None
    # Удвоенные скобки — валидный способ показать символ.
    assert validate_override(spec, "Привет {{друг}}") is None


# --------------------------- get_text / render_text ---------------------------


@pytest.mark.asyncio
async def test_get_text_default_and_override() -> None:
    spec = REGISTRY[bot_texts.KEY_LIKE_PUSH_ONE]
    assert await get_text(_StubSettings(), spec.key) == spec.default
    repo = _StubSettings({spec.key: "Кастомный текст"})
    assert await get_text(repo, spec.key) == "Кастомный текст"
    # Пустой оверрайд = дефолт.
    repo = _StubSettings({spec.key: "   "})
    assert await get_text(repo, spec.key) == spec.default


@pytest.mark.asyncio
async def test_get_text_survives_repo_failure() -> None:
    spec = REGISTRY[bot_texts.KEY_LIKE_PUSH_ONE]
    assert await get_text(_StubSettings(fail=True), spec.key) == spec.default


@pytest.mark.asyncio
async def test_render_text_formats_override() -> None:
    key = bot_texts.KEY_LIKE_PUSH_MANY
    repo = _StubSettings({key: "Целых {n} лайков!"})
    assert await render_text(repo, key, n=7) == "Целых 7 лайков!"


@pytest.mark.asyncio
async def test_render_text_falls_back_on_broken_override() -> None:
    """Кривой шаблон в БД (мимо валидации) → дефолт, не исключение."""
    key = bot_texts.KEY_LIKE_PUSH_MANY
    spec = REGISTRY[key]
    repo = _StubSettings({key: "Лайков: {oops}"})
    assert await render_text(repo, key, n=3) == spec.default.format(n=3)


@pytest.mark.asyncio
async def test_render_text_without_kwargs_keeps_literal_braces() -> None:
    key = bot_texts.KEY_WELCOME
    repo = _StubSettings({key: "Привет {{друг}}"})
    # Без kwargs подстановка не вызывается — текст уходит как сохранён.
    assert await render_text(repo, key) == "Привет {{друг}}"
