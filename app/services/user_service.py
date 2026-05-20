from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.complaint_repo import ComplaintRepository
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.services.analytics_events import EventType


async def delete_user_data(user: User, session: AsyncSession) -> None:
    """Удаление анкеты и всех пользовательских данных.

    Физически удаляется:
    1. Социальные данные: лайки, дизлайки, мэтчи, блоки, просмотры (скипы).
    2. Жалобы, где пользователь — автор или цель.
    3. Профиль (каскадно удаляет M2M-связи).

    Запись `users` НЕ трогается: аккаунт сохраняется, статус (Premium,
    модератор, админ по telegram_id) остаётся, бан не ставится. После
    удаления пользователь начинает с чистого листа и может создать анкету
    заново как новый.

    Платежи и аналитика НЕ удаляются: нужны для бухгалтерии и метрик.

    Операция выполняется в рамках одной внешней транзакции: вызывающий код
    должен управлять session.begin() / commit() / rollback() самостоятельно.
    """
    user_id = user.id
    logger.info("delete_user_data: starting profile deletion for user_id={}", user_id)

    matching_repo = MatchingRepository(session)
    await matching_repo.delete_user_social_data(user_id)

    complaint_repo = ComplaintRepository(session)
    await complaint_repo.delete_by_user(user_id)

    profile_repo = ProfileRepository(session)
    await profile_repo.delete_by_user_id(user_id)

    await AnalyticsRepository(session).log_event(user_id, event_type=EventType.PROFILE_DELETED)

    await session.flush()
    logger.info("delete_user_data: completed profile deletion for user_id={}", user_id)
