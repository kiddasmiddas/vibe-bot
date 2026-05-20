"""Меню команд бота (`bot.set_my_commands`).

Публичный список (`/start`, `/premium`, `/delete`) виден всем; расширенный
(с `/admin`) — только env-администраторам из `settings.admin_telegram_ids`
через персональный `BotCommandScopeChat`.

Модераторам (`User.is_moderator`) команда `/admin` в меню не показывается —
их список известен только из БД и меняется в рантайме, а меню команд это
подсказка, а не контроль доступа: реальная проверка прав — в хэндлере
`/admin`. Модератор может набрать `/admin` вручную.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from loguru import logger

from app.config import settings
from app.texts import commands as texts


def _public_commands() -> list[BotCommand]:
    """Команды, видимые всем пользователям."""
    return [
        BotCommand(command="start", description=texts.CMD_START),
        BotCommand(command="premium", description=texts.CMD_PREMIUM),
        BotCommand(command="delete", description=texts.CMD_DELETE),
    ]


def _admin_commands() -> list[BotCommand]:
    """Команды для env-администраторов: публичные + `/admin`."""
    return [
        *_public_commands(),
        BotCommand(command="admin", description=texts.CMD_ADMIN),
    ]


async def setup_bot_commands(bot: Bot) -> None:
    """Регистрирует меню команд в Telegram.

    Идемпотентно — `set_my_commands` перезаписывает список, безопасно
    вызывать при каждом старте. Сетевые ошибки логируются, но не роняют
    запуск бота ().
    """
    try:
        await bot.set_my_commands(_public_commands(), scope=BotCommandScopeDefault())
    except TelegramAPIError as exc:  # pragma: no cover — telegram-сеть
        logger.warning("set_my_commands(default) failed: {}", exc)

    admin_commands = _admin_commands()
    for admin_id in settings.admin_telegram_ids:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramAPIError as exc:  # pragma: no cover — telegram-сеть
            logger.warning("set_my_commands(chat={}) failed: {}", admin_id, exc)
