"""Доменные исключения сервисного слоя.

Используются вместо bare Exception в публичных API сервисов. Каждый сервис может
бросать только эти (или их подклассы) — это даёт хэндлерам предсказуемый набор
ошибок для перехвата и преобразования в пользовательские сообщения.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Базовый класс для всех сервисных исключений."""


class AlreadyPremiumError(ServiceError):
    """Пользователь уже имеет активный Premium.

    Используется в `PaymentService.create_premium_invoice` чтобы хэндлер мог
    отобразить корректное сообщение без попытки создать повторный инвойс.
    """

    def __init__(self, until: object) -> None:
        super().__init__(f"premium active until {until}")
        self.until = until


class PaymentProviderUnavailableError(ServiceError):
    """Провайдер платежей не настроен (пустой YOOKASSA_PROVIDER_TOKEN).

    В dev-окружении используется как ожидаемое состояние — без токена ЮKassa
    реальные платежи невозможны. Хэндлер отображает generic-сообщение пользователю
    и пишет warning в лог.
    """


class ContentRejectedError(ServiceError):
    """Контент отклонён модерацией.

    Используется в местах, где удобнее работать через ``except`` (например, в
    сервисе мэтчинга при создании лайка с сообщением). Текстовая проверка
    (`ContentModerationService.check_text`) сама исключений НЕ бросает —
    она возвращает структурированный `TextModerationResult`.
    """

    def __init__(self, reason: str, matched_terms: list[str] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.matched_terms = matched_terms or []
