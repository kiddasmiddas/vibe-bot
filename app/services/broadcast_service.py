from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.promo import PromoPost
from app.db.repositories.promo_repo import PromoRepository
from app.db.repositories.user_repo import UserRepository

# Максимальное число сообщений в секунду согласно лимитам Telegram Bot API.
_BATCH_SIZE = 25
# Пауза между батчами (секунды).
_BATCH_SLEEP = 1.0


@dataclass
class BroadcastResult:
    sent: int
    failed: int
    skipped: int


class BroadcastService:
    """Батчевая рассылка промо-поста пользователям.

    Поддерживает идемпотентность: если получатель уже имеет status='sent',
    он пропускается при повторном запуске.
    """

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._session = session
        self._bot = bot
        self._promo_repo = PromoRepository(session)
        self._user_repo = UserRepository(session)

    async def run(self, promo_post_id: int) -> BroadcastResult:
        """Запускает рассылку для PromoPost с данным id.

        Допустимые стартовые статусы: ``draft`` и ``queued``.
        Возвращает BroadcastResult(sent, failed, skipped).
        Raises ValueError если пост не найден или находится в недопустимом статусе.
        """
        post = await self._promo_repo.get_by_id(promo_post_id)
        if post is None:
            raise ValueError(f"PromoPost {promo_post_id} not found")
        if post.status not in ("draft", "queued"):
            raise ValueError(
                f"PromoPost {promo_post_id} has status={post.status!r}; "
                "expected 'draft' or 'queued'"
            )

        # Переводим в статус «отправляется».
        await self._promo_repo.update(
            promo_post_id,
            status="sending",
            started_at=datetime.now(tz=UTC),
        )
        logger.info("broadcast started: promo_post_id={}", promo_post_id)

        # Готовим список получателей.
        await self._prepare_recipients(post)

        # Забираем только pending-получателей (идемпотентность: sent пропускаем).
        recipients = await self._promo_repo.list_pending_recipients(promo_post_id)
        logger.info(
            "broadcast recipients: promo_post_id={} pending={}",
            promo_post_id,
            len(recipients),
        )

        sent = 0
        failed = 0
        skipped = 0

        for i, recipient in enumerate(recipients):
            # Подгружаем свежий статус получателя, чтобы пропустить уже отправленных
            # при параллельных запусках.
            fresh_recipient = await self._promo_repo.get_recipient(promo_post_id, recipient.user_id)
            if fresh_recipient is not None and fresh_recipient.status == "sent":
                skipped += 1
                continue

            user = await self._user_repo.get_by_id(recipient.user_id)
            if user is None:
                await self._promo_repo.mark_recipient_failed(
                    promo_post_id, recipient.user_id, "user_not_found"
                )
                failed += 1
                continue

            success = await self._send_to_user(post, user.telegram_id)
            if success is True:
                await self._promo_repo.mark_recipient_sent(promo_post_id, recipient.user_id)
                sent += 1
            elif success is None:
                # Пользователь заблокировал бота — помечаем failed, не останавливаемся.
                await self._promo_repo.mark_recipient_failed(
                    promo_post_id, recipient.user_id, "forbidden"
                )
                failed += 1
            else:
                # success — строка с описанием ошибки.
                await self._promo_repo.mark_recipient_failed(
                    promo_post_id, recipient.user_id, str(success)
                )
                failed += 1

            # Батчинг: после каждых BATCH_SIZE сообщений — пауза 1 секунду.
            if (i + 1) % _BATCH_SIZE == 0:
                await asyncio.sleep(_BATCH_SLEEP)

        # Финал: статус failed если ни одного успешного при наличии ошибок.
        final_status = "failed" if sent == 0 and failed > 0 else "sent"
        await self._promo_repo.update(
            promo_post_id,
            status=final_status,
            finished_at=datetime.now(tz=UTC),
        )
        await self._promo_repo.recount_progress(promo_post_id)

        logger.info(
            "broadcast finished: promo_post_id={} sent={} failed={} skipped={}",
            promo_post_id,
            sent,
            failed,
            skipped,
        )
        return BroadcastResult(sent=sent, failed=failed, skipped=skipped)

    async def _prepare_recipients(self, post: PromoPost) -> None:
        """Создаёт записи в promo_post_recipients для нужного сегмента.

        Для ``custom`` сегмента записи уже должны быть в БД (модератор залил сам).
        Для остальных сегментов — выбираем пользователей из user_repo.
        Согласно §9.2 ТЗ: Premium исключаются из ``all`` и ``free``.
        """
        if post.target_segment == "custom":
            # Записи уже есть, ничего не создаём.
            return

        users = await self._user_repo.list_by_segment(post.target_segment)

        # §9.2: для сегментов all и free — исключаем premium-пользователей.
        if post.target_segment in ("all", "free"):
            users = [u for u in users if not u.is_premium]

        user_ids = [u.id for u in users]
        await self._promo_repo.add_recipients(post.id, user_ids)
        logger.info(
            "broadcast recipients prepared: promo_post_id={} segment={} count={}",
            post.id,
            post.target_segment,
            len(user_ids),
        )

    async def _send_to_user(self, post: PromoPost, telegram_id: int) -> bool | None | str:
        """Отправляет сообщение пользователю.

        Возвращает:
        - ``True``  — успешно отправлено.
        - ``None``  — пользователь заблокировал бота (TelegramForbiddenError).
        - ``str``   — описание ошибки TelegramAPIError.
        """
        try:
            await self._do_send(post, telegram_id)
            return True
        except TelegramForbiddenError:
            logger.warning("broadcast: user blocked bot telegram_id={}", telegram_id)
            return None
        except TelegramRetryAfter as exc:
            logger.warning(
                "broadcast: rate limited, retry after {}s (telegram_id={})",
                exc.retry_after,
                telegram_id,
            )
            await asyncio.sleep(exc.retry_after)
            # Один повтор после ожидания.
            try:
                await self._do_send(post, telegram_id)
                return True
            except TelegramForbiddenError:
                return None
            except TelegramAPIError as retry_exc:
                logger.error(
                    "broadcast: retry failed telegram_id={} error={}",
                    telegram_id,
                    retry_exc,
                )
                return str(retry_exc)
        except TelegramAPIError as exc:
            logger.error(
                "broadcast: send failed telegram_id={} error={}",
                telegram_id,
                exc,
            )
            return str(exc)

    async def _do_send(self, post: PromoPost, telegram_id: int) -> None:
        """Непосредственная отправка: текст, photo, video или animation."""
        if post.media_file_id and post.media_type:
            if post.media_type == "photo":
                await self._bot.send_photo(
                    chat_id=telegram_id,
                    photo=post.media_file_id,
                    caption=post.text,
                )
            elif post.media_type == "video":
                await self._bot.send_video(
                    chat_id=telegram_id,
                    video=post.media_file_id,
                    caption=post.text,
                )
            elif post.media_type == "animation":
                await self._bot.send_animation(
                    chat_id=telegram_id,
                    animation=post.media_file_id,
                    caption=post.text,
                )
            else:
                # Неизвестный media_type — отправляем только текст.
                await self._bot.send_message(chat_id=telegram_id, text=post.text)
        else:
            await self._bot.send_message(chat_id=telegram_id, text=post.text)
