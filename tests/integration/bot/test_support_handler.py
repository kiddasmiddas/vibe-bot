from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.handlers.support import SUPPORT_CONTACT_KEY, on_support
from app.db.repositories.settings_repo import SettingsRepository
from app.texts import common as texts


@pytest.mark.asyncio
async def test_support_handler_uses_configured_contact(db_session) -> None:
    contact = "@vibe_support_bot"
    await SettingsRepository(db_session).set(SUPPORT_CONTACT_KEY, contact)
    await db_session.flush()

    message = MagicMock()
    message.answer = AsyncMock()

    await on_support(message, db_session)

    sent = message.answer.call_args.args[0]
    assert contact in sent
    assert texts.RULES_FALLBACK_CONTACT not in sent


@pytest.mark.asyncio
async def test_support_handler_falls_back_when_contact_empty(db_session) -> None:
    # Seed-миграция кладёт пустую строку для support_contact.
    await SettingsRepository(db_session).set(SUPPORT_CONTACT_KEY, "")
    await db_session.flush()

    message = MagicMock()
    message.answer = AsyncMock()

    await on_support(message, db_session)

    sent = message.answer.call_args.args[0]
    assert texts.RULES_FALLBACK_CONTACT in sent
