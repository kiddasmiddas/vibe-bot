"""Интеграционные тесты BroadcastService против реальной тестовой БД.

Bot-объект заменяется AsyncMock — к Telegram API запросы не идут.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from app.db.models.promo import PromoPost
from app.db.repositories.promo_repo import PromoRepository
from app.db.repositories.user_repo import UserRepository
from app.services.broadcast_service import BroadcastService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(
    db_session,
    telegram_id: int,
    *,
    is_banned: bool = False,
    is_premium: bool = False,
):
    repo = UserRepository(db_session)
    user = await repo.create(telegram_id=telegram_id)
    if is_banned or is_premium:
        from sqlalchemy import update

        from app.db.models.user import User

        stmt = (
            update(User)
            .where(User.id == user.id)
            .values(is_banned=is_banned, is_premium=is_premium)
        )
        await db_session.execute(stmt)
        await db_session.flush()
        await db_session.refresh(user)
    return user


async def _make_post(db_session, *, segment: str = "all", status: str = "draft") -> PromoPost:
    repo = PromoRepository(db_session)
    post = await repo.create_draft(
        text="Test broadcast message",
        target_segment=segment,
        status=status,
    )
    return post


def _make_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=None)
    bot.send_photo = AsyncMock(return_value=None)
    bot.send_video = AsyncMock(return_value=None)
    bot.send_animation = AsyncMock(return_value=None)
    return bot


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_segment_all_excludes_premium_and_banned(db_session):
    """segment=all отправляет только не-premium и не-banned пользователям."""
    regular = await _make_user(db_session, telegram_id=9_001_001)
    _premium = await _make_user(db_session, telegram_id=9_001_002, is_premium=True)
    _banned = await _make_user(db_session, telegram_id=9_001_003, is_banned=True)

    post = await _make_post(db_session, segment="all")
    bot = _make_bot()

    service = BroadcastService(session=db_session, bot=bot)
    result = await service.run(post.id)

    assert result.sent == 1
    assert result.failed == 0
    # Проверяем, что отправка была именно regular-пользователю.
    bot.send_message.assert_called_once_with(chat_id=regular.telegram_id, text=post.text)


@pytest.mark.asyncio
async def test_segment_premium_only_premium(db_session):
    """segment=premium отправляет только premium-пользователям."""
    _regular = await _make_user(db_session, telegram_id=9_002_001)
    premium = await _make_user(db_session, telegram_id=9_002_002, is_premium=True)
    _banned_premium = await _make_user(
        db_session, telegram_id=9_002_003, is_premium=True, is_banned=True
    )

    post = await _make_post(db_session, segment="premium")
    bot = _make_bot()

    service = BroadcastService(session=db_session, bot=bot)
    result = await service.run(post.id)

    assert result.sent == 1
    bot.send_message.assert_called_once_with(chat_id=premium.telegram_id, text=post.text)


@pytest.mark.asyncio
async def test_segment_free_excludes_premium_and_banned(db_session):
    """segment=free отправляет только не-premium и не-banned пользователям."""
    free_user = await _make_user(db_session, telegram_id=9_003_001)
    _premium = await _make_user(db_session, telegram_id=9_003_002, is_premium=True)
    _banned = await _make_user(db_session, telegram_id=9_003_003, is_banned=True)

    post = await _make_post(db_session, segment="free")
    bot = _make_bot()

    service = BroadcastService(session=db_session, bot=bot)
    result = await service.run(post.id)

    assert result.sent == 1
    bot.send_message.assert_called_once_with(chat_id=free_user.telegram_id, text=post.text)


@pytest.mark.asyncio
async def test_forbidden_error_marks_failed_continues(db_session):
    """TelegramForbiddenError помечает получателя как failed, рассылка продолжается."""
    user_ok = await _make_user(db_session, telegram_id=9_004_001)
    user_blocked = await _make_user(db_session, telegram_id=9_004_002)

    post = await _make_post(db_session, segment="all")
    bot = _make_bot()

    # Первый вызов — успех, второй — forbidden (порядок по telegram_id не гарантирован,
    # поэтому side_effect зависит от фактического telegram_id).
    forbidden_exc = TelegramForbiddenError(
        method=None,  # type: ignore[arg-type]
        message="Forbidden: bot was blocked by the user",
    )

    call_count = 0

    async def send_side_effect(chat_id, text):
        nonlocal call_count
        call_count += 1
        if chat_id == user_blocked.telegram_id:
            raise forbidden_exc
        return None

    bot.send_message.side_effect = send_side_effect

    service = BroadcastService(session=db_session, bot=bot)
    result = await service.run(post.id)

    assert result.sent == 1
    assert result.failed == 1
    assert call_count == 2

    # Проверяем статусы в БД.
    from sqlalchemy import select as _select

    from app.db.models.promo import PromoPostRecipient as PPR

    ok_rec = (
        await db_session.execute(
            _select(PPR).where(
                PPR.promo_post_id == post.id,
                PPR.user_id == user_ok.id,
            )
        )
    ).scalar_one_or_none()
    blocked_rec = (
        await db_session.execute(
            _select(PPR).where(
                PPR.promo_post_id == post.id,
                PPR.user_id == user_blocked.id,
            )
        )
    ).scalar_one_or_none()

    assert ok_rec is not None and ok_rec.status == "sent"
    assert blocked_rec is not None and blocked_rec.status == "failed"
    assert blocked_rec.error == "forbidden"


@pytest.mark.asyncio
async def test_retry_after_retries_once_then_fails(db_session):
    """TelegramRetryAfter вызывает один retry; если снова ошибка — recipient failed."""
    user = await _make_user(db_session, telegram_id=9_005_001)
    post = await _make_post(db_session, segment="all")
    bot = _make_bot()

    retry_exc = TelegramRetryAfter(
        method=None,  # type: ignore[arg-type]
        message="Too Many Requests: retry after 1",
        retry_after=0,  # 0 секунд — тест не тормозит
    )
    api_error = TelegramAPIError(
        method=None,  # type: ignore[arg-type]
        message="Internal Server Error",
    )

    # Первый вызов — RetryAfter; второй — обычная ошибка (retry провалился).
    bot.send_message.side_effect = [retry_exc, api_error]

    with patch("app.services.broadcast_service.asyncio.sleep", new_callable=AsyncMock):
        service = BroadcastService(session=db_session, bot=bot)
        result = await service.run(post.id)

    assert result.sent == 0
    assert result.failed == 1

    from sqlalchemy import select as _select

    from app.db.models.promo import PromoPostRecipient as PPR

    rec = (
        await db_session.execute(
            _select(PPR).where(
                PPR.promo_post_id == post.id,
                PPR.user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    assert rec is not None and rec.status == "failed"
    assert rec.error is not None


@pytest.mark.asyncio
async def test_retry_after_success_on_retry(db_session):
    """TelegramRetryAfter + успешный retry → recipient sent."""
    await _make_user(db_session, telegram_id=9_006_001)
    post = await _make_post(db_session, segment="all")
    bot = _make_bot()

    retry_exc = TelegramRetryAfter(
        method=None,  # type: ignore[arg-type]
        message="Too Many Requests: retry after 0",
        retry_after=0,
    )
    # Первый вызов — RetryAfter; второй — успех.
    bot.send_message.side_effect = [retry_exc, None]

    with patch("app.services.broadcast_service.asyncio.sleep", new_callable=AsyncMock):
        service = BroadcastService(session=db_session, bot=bot)
        result = await service.run(post.id)

    assert result.sent == 1
    assert result.failed == 0


@pytest.mark.asyncio
async def test_idempotency_skips_sent_recipients(db_session):
    """Повторный запуск пропускает получателей со status='sent'."""
    await _make_user(db_session, telegram_id=9_007_001)
    post = await _make_post(db_session, segment="all")

    # Первый успешный запуск.
    bot = _make_bot()
    service = BroadcastService(session=db_session, bot=bot)
    result1 = await service.run(post.id)
    assert result1.sent == 1

    # Переводим пост обратно в 'draft', чтобы можно было перезапустить.
    from sqlalchemy import update

    from app.db.models.promo import PromoPost as PP

    await db_session.execute(update(PP).where(PP.id == post.id).values(status="draft"))
    await db_session.flush()

    # Второй запуск — pending список пустой (все уже sent).
    bot2 = _make_bot()
    service2 = BroadcastService(session=db_session, bot=bot2)
    result2 = await service2.run(post.id)

    assert result2.sent == 0
    assert result2.failed == 0
    # send_message не вызывался во втором запуске.
    bot2.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_status_raises_value_error(db_session):
    """run() бросает ValueError, если пост в статусе 'sending' или 'sent'."""
    post = await _make_post(db_session, segment="all", status="draft")

    from sqlalchemy import update

    from app.db.models.promo import PromoPost as PP

    await db_session.execute(update(PP).where(PP.id == post.id).values(status="sending"))
    await db_session.flush()

    bot = _make_bot()
    service = BroadcastService(session=db_session, bot=bot)
    with pytest.raises(ValueError, match="status="):
        await service.run(post.id)


@pytest.mark.asyncio
async def test_post_not_found_raises_value_error(db_session):
    """run() бросает ValueError для несуществующего promo_post_id."""
    bot = _make_bot()
    service = BroadcastService(session=db_session, bot=bot)
    with pytest.raises(ValueError, match="not found"):
        await service.run(999_999_999)


@pytest.mark.asyncio
async def test_segment_custom_uses_existing_recipients(db_session):
    """segment=custom — берёт уже подготовленных получателей из promo_post_recipients."""
    user = await _make_user(db_session, telegram_id=9_009_001)
    post = await _make_post(db_session, segment="custom")

    # Добавляем получателя вручную (как делает модератор).
    promo_repo = PromoRepository(db_session)
    await promo_repo.add_recipients(post.id, [user.id])

    bot = _make_bot()
    service = BroadcastService(session=db_session, bot=bot)
    result = await service.run(post.id)

    assert result.sent == 1
    bot.send_message.assert_called_once_with(chat_id=user.telegram_id, text=post.text)
