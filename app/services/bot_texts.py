"""Редактируемые тексты бота: реестр, чтение с fallback, безопасный format.

Клиент правит тексты кнопками в /admin (сырые ключи ему не показываются):
оверрайд хранится в app_settings (ключи `text_*`), отсутствие записи или
пустое значение = дефолт из `app/texts`. Кривой шаблон (лишний/битый
{плейсхолдер}) не роняет отправку — подстановка откатывается на дефолт с логом.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape as _html_escape

from loguru import logger

from app.db.repositories.settings_repo import SettingsRepository
from app.texts import bot_texts_admin as admin_texts
from app.texts import common as common_texts
from app.texts import matching as matching_texts
from app.texts import notifications as notif_texts

# Лимиты на ввод админа: кнопка обрезается Telegram визуально, сообщение
# упирается в 4096. Бюджет шаблона держим с запасом под подстановку
# HTML-экранированного пользовательского текста (ник ≤32→~160, суперлайк-
# сообщение ≤200→~1000 после html.escape) — иначе итог пуша пробьёт 4096 и
# Telegram молча его отклонит.
TELEGRAM_MESSAGE_LIMIT = 4096
_SUBSTITUTION_RESERVE = 1200
MAX_LEN_BUTTON = 64
MAX_LEN_MESSAGE = TELEGRAM_MESSAGE_LIMIT - _SUBSTITUTION_RESERVE  # 2896


@dataclass(frozen=True)
class EditableText:
    """Одна редактируемая позиция: ключ app_settings + дефолт + плейсхолдеры."""

    key: str  # ключ app_settings (text_*)
    label: str  # название кнопки в админ-списке
    default: str  # дефолт из app/texts
    placeholders: tuple[str, ...] = ()  # допустимые {имена}
    hint: str = ""  # расшифровка плейсхолдеров для админа
    max_len: int = MAX_LEN_MESSAGE
    # Кнопки Telegram не парсятся как HTML: редактор хранит для них plain
    # message.text; для сообщений — message.html_text (форматирование админа
    # сохраняется, спецсимволы экранирует aiogram).
    is_button: bool = False
    # Ключ inline-кнопки под этим сообщением (если есть): на карточке карусели
    # появляется вторая кнопка «✏️ Кнопка», редактирующая её текст. Сами кнопки
    # живут в BUTTON_TEXTS (в реестре, но не листаются отдельными карточками).
    button_key: str | None = None


# Ключи app_settings редактируемых текстов (используются на местах отправки).
KEY_LIKE_PUSH_ONE = "text_like_push_one"
KEY_LIKE_PUSH_MANY = "text_like_push_many"
KEY_SUPERLIKE_PUSH = "text_superlike_push"
KEY_SUPERLIKE_PUSH_MSG = "text_superlike_push_msg"
KEY_MATCH_PUSH = "text_match_push"
KEY_MATCH_PUSH_MSG = "text_match_push_msg"
KEY_COMMENT_PUSH = "text_comment_push"
KEY_REPLY_PUSH = "text_reply_push"
KEY_BTN_VIEW_LIKES = "text_btn_view_likes"
KEY_BTN_OPEN_POST = "text_btn_open_post"
KEY_BTN_OPEN_PROFILE = "text_btn_open_profile"
KEY_WELCOME = "text_welcome"
KEY_RULES = "text_rules"

# Группа «Уведомления» — редактируется из /admin → 🔔 Уведомления → ✏️ Тексты.
# `button_key` связывает пуш с его inline-кнопкой: на карточке появляется вторая
# кнопка «✏️ Кнопка», а сами кнопки не листаются отдельными карточками.
NOTIF_TEXTS: tuple[EditableText, ...] = (
    EditableText(
        KEY_LIKE_PUSH_ONE,
        "❤️ Лайк (разовое)",
        notif_texts.LIKE_PUSH_ONE,
        button_key=KEY_BTN_VIEW_LIKES,
    ),
    EditableText(
        KEY_LIKE_PUSH_MANY,
        "❤️ Лайки — сводка",
        notif_texts.LIKE_PUSH_MANY,
        ("n",),
        "{n} — число новых лайков",
        button_key=KEY_BTN_VIEW_LIKES,
    ),
    EditableText(
        KEY_SUPERLIKE_PUSH,
        "⭐ Суперлайк",
        notif_texts.SUPERLIKE_PUSH,
        button_key=KEY_BTN_VIEW_LIKES,
    ),
    EditableText(
        KEY_SUPERLIKE_PUSH_MSG,
        "⭐ Суперлайк с сообщением",
        notif_texts.SUPERLIKE_PUSH_WITH_MESSAGE,
        ("message",),
        "{message} — сообщение отправителя",
        button_key=KEY_BTN_VIEW_LIKES,
    ),
    EditableText(
        KEY_MATCH_PUSH,
        "🎉 Мэтч",
        matching_texts.MATCH_HEADER,
        ("nickname",),
        "{nickname} — ник второго участника",
        button_key=KEY_BTN_OPEN_PROFILE,
    ),
    EditableText(
        KEY_MATCH_PUSH_MSG,
        "🎉 Мэтч с сообщением",
        matching_texts.MATCH_WITH_MESSAGE,
        ("nickname", "message"),
        "{nickname} — ник второго участника, {message} — сообщение",
        button_key=KEY_BTN_OPEN_PROFILE,
    ),
    EditableText(
        KEY_COMMENT_PUSH,
        "💬 Комментарий к посту",
        notif_texts.COMMENT_PUSH_ONE,
        ("preview",),
        "{preview} — начало комментария",
        button_key=KEY_BTN_OPEN_POST,
    ),
    EditableText(
        KEY_REPLY_PUSH,
        "↩️ Ответ на комментарий",
        notif_texts.REPLY_PUSH,
        ("preview",),
        "{preview} — начало ответа",
        button_key=KEY_BTN_OPEN_POST,
    ),
)

# Группа «Приветственные» — редактируется из /admin → ⚙️ Настройки.
GENERAL_TEXTS: tuple[EditableText, ...] = (
    EditableText(KEY_WELCOME, "👋 Приветствие /start", common_texts.WELCOME),
    EditableText(
        KEY_RULES,
        "📖 Правила / поддержка",
        common_texts.RULES_BODY,
        ("contact",),
        "{contact} — контакт поддержки (настройка support_contact)",
    ),
)

# Тексты inline-кнопок под пушами. В реестре (доступны get_text и редактору
# через button_key), но НЕ листаются каруселью отдельными карточками.
BUTTON_TEXTS: tuple[EditableText, ...] = (
    EditableText(
        KEY_BTN_VIEW_LIKES,
        "Кнопка «Посмотреть»",
        notif_texts.BTN_VIEW_LIKES,
        max_len=MAX_LEN_BUTTON,
        is_button=True,
    ),
    EditableText(
        KEY_BTN_OPEN_POST,
        "Кнопка «Открыть пост»",
        notif_texts.BTN_OPEN_POST,
        max_len=MAX_LEN_BUTTON,
        is_button=True,
    ),
    EditableText(
        KEY_BTN_OPEN_PROFILE,
        "Кнопка «Открыть профиль»",
        matching_texts.BTN_OPEN_PROFILE,
        max_len=MAX_LEN_BUTTON,
        is_button=True,
    ),
)

GROUPS: dict[str, tuple[EditableText, ...]] = {
    "notif": NOTIF_TEXTS,
    "general": GENERAL_TEXTS,
}

REGISTRY: dict[str, EditableText] = {
    t.key: t for t in (*NOTIF_TEXTS, *GENERAL_TEXTS, *BUTTON_TEXTS)
}


# Единственная легальная форма плейсхолдера — `{имя}` (имя = [A-Za-z0-9_]+);
# `{{`/`}}` — литеральные скобки. НАМЕРЕННО не используем str.format: его
# протокол рекурсивно раскрывает вложенные поля в format-spec (`{a:{b}}`),
# что позволяет одному подставляемому значению управлять рендером другого —
# включая width-инъекцию (цифровая строка юзера → аллокация гигантской строки,
# блокировка event-loop) и обход allowlist'а атрибутным доступом. Своя
# regex-подстановка не вызывает ни __format__, ни getattr.
_TOKEN_RE = re.compile(r"\{\{|\}\}|\{(\w+)\}")


def extract_placeholders(template: str) -> set[str] | None:
    """Имена `{плейсхолдеров}` шаблона; None — есть недопустимая скобка.

    Допустимы только `{{`, `}}` и `{имя}` (имя = \\w+). Любая другая скобочная
    конструкция — одиночная `{`/`}`, `{}`, `{0}`, `{x.attr}`, `{a:{b}}` —
    считается битой (None): рендер такой шаблон не раскроет, значит и сохранять
    его нельзя.
    """
    names: set[str] = set()
    i, n = 0, len(template)
    while i < n:
        ch = template[i]
        if ch in "{}":
            if template[i : i + 2] in ("{{", "}}"):
                i += 2
                continue
            if ch == "{":
                m = _TOKEN_RE.match(template, i)
                if m is not None and m.group(1) is not None:
                    names.add(m.group(1))
                    i = m.end()
                    continue
            # Одиночная `{`/`}` или недопустимое содержимое поля.
            return None
        i += 1
    return names


def safe_substitute(template: str, mapping: dict[str, str]) -> str:
    """Подстановка `{имя}` из mapping без вызова протокола format().

    `{{`/`}}` → литеральные `{`/`}`; `{имя}` без значения в mapping остаётся
    как есть (не роняем на пропущенном ключе). Атрибутный доступ, индексация
    и format-spec невозможны в принципе — токенайзер их не распознаёт.
    """

    def _repl(m: re.Match[str]) -> str:
        token = m.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        return str(mapping.get(m.group(1), token))

    return _TOKEN_RE.sub(_repl, template)


def validate_override(spec: EditableText, value: str) -> str | None:
    """Проверка текста от админа; возвращает текст ошибки или None (ок)."""
    if not value.strip():
        return admin_texts.ERR_EMPTY
    if len(value) > spec.max_len:
        return admin_texts.ERR_TOO_LONG.format(max_len=spec.max_len)
    found = extract_placeholders(value)
    if found is None:
        return admin_texts.ERR_BAD_BRACES
    unknown = found - set(spec.placeholders)
    if unknown:
        # Текст ошибки уходит сообщением с parse_mode=HTML — имена из ввода
        # админа экранируем.
        return admin_texts.ERR_UNKNOWN_PLACEHOLDER.format(
            unknown=_html_escape(", ".join(sorted(f"{{{p}}}" for p in unknown))),
            allowed=placeholders_hint(spec),
        )
    return None


def placeholders_hint(spec: EditableText) -> str:
    """Строка-подсказка о допустимых плейсхолдерах (для промпта админу)."""
    if not spec.placeholders:
        return admin_texts.HINT_NO_PLACEHOLDERS
    return spec.hint or ", ".join(f"{{{p}}}" for p in spec.placeholders)


async def get_text(settings_repo: SettingsRepository, key: str) -> str:
    """Актуальный шаблон: оверрайд админа из app_settings или дефолт из кода.

    Ошибка чтения настроек не пробрасывается — тексты не повод ронять
    отправку сообщения.
    """
    spec = REGISTRY[key]
    try:
        value = await settings_repo.get(spec.key)
    except Exception as exc:
        logger.warning("bot_texts.get_text({}): чтение упало ({}) — дефолт", key, exc)
        return spec.default
    if value is None or not value.strip():
        return spec.default
    return value


async def render_text(settings_repo: SettingsRepository, key: str, **kwargs: object) -> str:
    """get_text + безопасная подстановка плейсхолдеров с откатом на дефолт.

    Подстановка идёт через `safe_substitute` (без протокола format), поэтому
    кривой оверрайд не роняет отправку и не даёт width-/attr-инъекций. Значения
    приводятся к str; литеральные `{{`/`}}` схлопываются и в шаблоне без kwargs.
    """
    spec = REGISTRY[key]
    template = await get_text(settings_repo, key)
    mapping = {k: str(v) for k, v in kwargs.items()}
    try:
        result = safe_substitute(template, mapping)
    except Exception as exc:
        logger.warning(
            "bot_texts.render_text({}): кривой оверрайд {!r} ({}) — дефолт",
            key,
            template[:80],
            exc,
        )
        result = safe_substitute(spec.default, mapping)
    # Предохранитель: даже при запасе _SUBSTITUTION_RESERVE итог не должен
    # пробить 4096 (иначе Telegram молча отклонит sendMessage). Кнопки
    # читаются через get_text и ограничены валидацией — их тут нет.
    if len(result) > TELEGRAM_MESSAGE_LIMIT:
        result = result[: TELEGRAM_MESSAGE_LIMIT - 1] + "…"
    return result
