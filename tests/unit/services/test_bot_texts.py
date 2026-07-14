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
    # Любая недопустимая скобочная конструкция → None (нельзя сохранять).
    assert extract_placeholders("оборванная {") is None
    assert extract_placeholders("непарная }") is None
    assert extract_placeholders("{}") is None
    assert extract_placeholders("{n.__class__}") is None
    # Вложенное поле в format-spec (вектор width-инъекции) — тоже None.
    assert extract_placeholders("{nickname:{message}}") is None
    # `{0}` синтаксически валиден (имя = "0"), но не совпадёт с allow-списком
    # ни одного текста → validate_override отклонит его как unknown.
    assert extract_placeholders("{0}") == {"0"}


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
async def test_render_text_unknown_placeholder_left_literal() -> None:
    """Кривой шаблон в БД (мимо валидации) → неизвестное поле остаётся как есть,
    без исключения и без раскрытия чужих значений."""
    key = bot_texts.KEY_LIKE_PUSH_MANY
    repo = _StubSettings({key: "Лайков: {oops} ({n})"})
    assert await render_text(repo, key, n=3) == "Лайков: {oops} (3)"


@pytest.mark.asyncio
async def test_render_text_collapses_literal_braces_without_kwargs() -> None:
    """`{{`/`}}` схлопываются в литералы даже у текста без плейсхолдеров
    (закрыта Medium из ревью: раньше уходили задвоенными)."""
    key = bot_texts.KEY_WELCOME
    repo = _StubSettings({key: "Привет {{друг}}"})
    assert await render_text(repo, key) == "Привет {друг}"


@pytest.mark.asyncio
async def test_render_text_no_format_spec_injection() -> None:
    """Вложенное поле в format-spec не раскрывается: длинная цифровая строка
    юзера НЕ превращается в width-аллокацию (safe_substitute вместо .format)."""
    key = bot_texts.KEY_MATCH_PUSH_MSG
    repo = _StubSettings({key: "{nickname:{message}}"})
    # `.format` трактовал бы message="9"*9 как ширину → строка в 10^9 символов.
    # safe_substitute лишь подставляет {message} как текст: никакой аллокации.
    result = await render_text(repo, key, nickname="Боб", message="9" * 9)
    assert len(result) < 100
    assert "999999999" in result  # подставлено как литерал, не как width


@pytest.mark.asyncio
async def test_render_text_clamps_to_telegram_limit() -> None:
    """Итог не превышает 4096 даже при раздутой подстановке."""
    key = bot_texts.KEY_SUPERLIKE_PUSH_MSG
    repo = _StubSettings({key: "Сообщение: {message}"})
    result = await render_text(repo, key, message="x" * 5000)
    assert len(result) <= bot_texts.TELEGRAM_MESSAGE_LIMIT
