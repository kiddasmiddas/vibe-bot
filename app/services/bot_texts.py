"""Редактируемые тексты бота: реестр, чтение с fallback, безопасный format.

Клиент правит тексты кнопками в /admin (сырые ключи ему не показываются):
оверрайд хранится в app_settings (ключи `text_*`), отсутствие записи или
пустое значение = дефолт из `app/texts`. Кривой шаблон (лишний/битый
{плейсхолдер}) не роняет отправку — подстановка откатывается на дефолт с логом.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape as _html_escape
from string import Formatter

from loguru import logger

from app.db.repositories.settings_repo import SettingsRepository
from app.texts import bot_texts_admin as admin_texts
from app.texts import common as common_texts
from app.texts import matching as matching_texts
from app.texts import notifications as notif_texts

# Лимиты на ввод админа: кнопка обрезается Telegram визуально, сообщение
# упирается в 4096 (оставляем запас под parse_mode-сущности).
MAX_LEN_BUTTON = 64
MAX_LEN_MESSAGE = 3500


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
KEY_WELCOME = "text_welcome"
KEY_RULES = "text_rules"

# Группа «Уведомления» — редактируется из /admin → 🔔 Уведомления → ✏️ Тексты.
NOTIF_TEXTS: tuple[EditableText, ...] = (
    EditableText(KEY_LIKE_PUSH_ONE, "❤️ Лайк (разовое)", notif_texts.LIKE_PUSH_ONE),
    EditableText(
        KEY_LIKE_PUSH_MANY,
        "❤️ Лайки — сводка",
        notif_texts.LIKE_PUSH_MANY,
        ("n",),
        "{n} — число новых лайков",
    ),
    EditableText(KEY_SUPERLIKE_PUSH, "⭐ Суперлайк", notif_texts.SUPERLIKE_PUSH),
    EditableText(
        KEY_SUPERLIKE_PUSH_MSG,
        "⭐ Суперлайк с сообщением",
        notif_texts.SUPERLIKE_PUSH_WITH_MESSAGE,
        ("message",),
        "{message} — сообщение отправителя",
    ),
    EditableText(
        KEY_MATCH_PUSH,
        "🎉 Мэтч",
        matching_texts.MATCH_HEADER,
        ("nickname",),
        "{nickname} — ник второго участника",
    ),
    EditableText(
        KEY_MATCH_PUSH_MSG,
        "🎉 Мэтч с сообщением",
        matching_texts.MATCH_WITH_MESSAGE,
        ("nickname", "message"),
        "{nickname} — ник второго участника, {message} — сообщение",
    ),
    EditableText(
        KEY_COMMENT_PUSH,
        "💬 Комментарий к посту",
        notif_texts.COMMENT_PUSH_ONE,
        ("preview",),
        "{preview} — начало комментария",
    ),
    EditableText(
        KEY_REPLY_PUSH,
        "↩️ Ответ на комментарий",
        notif_texts.REPLY_PUSH,
        ("preview",),
        "{preview} — начало ответа",
    ),
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

GROUPS: dict[str, tuple[EditableText, ...]] = {
    "notif": NOTIF_TEXTS,
    "general": GENERAL_TEXTS,
}

REGISTRY: dict[str, EditableText] = {t.key: t for t in (*NOTIF_TEXTS, *GENERAL_TEXTS)}


def extract_placeholders(template: str) -> set[str] | None:
    """Имена {плейсхолдеров} шаблона; None — шаблон синтаксически битый.

    Позиционные `{}`/`{0}` и обращения вида `{x.attr}`/`{x[0]}` вернутся как
    есть и не совпадут с allowed-списком — валидация их отбросит (в т.ч.
    закрывает format-string-доступ к атрибутам).
    """
    try:
        return {fname for _, fname, _, _ in Formatter().parse(template) if fname is not None}
    except ValueError:
        return None


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
    """get_text + подстановка плейсхолдеров с откатом на дефолт при ошибке."""
    spec = REGISTRY[key]
    template = await get_text(settings_repo, key)
    if not kwargs:
        # Без подстановки шаблон уходит как есть (литеральные скобки легальны).
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError, AttributeError) as exc:
        logger.warning(
            "bot_texts.render_text({}): кривой оверрайд {!r} ({}) — дефолт",
            key,
            template[:80],
            exc,
        )
        return spec.default.format(**kwargs)
