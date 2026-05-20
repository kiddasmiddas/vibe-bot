"""Сервис контент-модерации (текст).

Реализует Промпт 3.5.1: проверка текста по стоп-листам из БД + встроенные
регулярки на ссылки. NSFW-проверка изображений — отдельный сервис (3.5.2).

.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from loguru import logger

from app.config import settings as app_settings
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.services.nudenet_singleton import get_nudenet_detector
from app.services.text_normalization import (
    normalize_for_link_detection,
    normalize_for_moderation,
)

# Нижняя граница «серой зоны»: ниже — approved, между этим и threshold —
# manual_review, выше или равно threshold — rejected.
MANUAL_REVIEW_LOW_BOUND = 0.4

# Встроенные паттерны на ссылки. Дублируем регексы из seed-миграции 2b3e153c704a,
# чтобы оставаться стабильно работоспособными даже если админ деактивировал
# link-регэксы в БД ( — defence in depth).
_LINK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bhttps?://\S+", flags=re.IGNORECASE),
    re.compile(r"\bt\.me/\S+", flags=re.IGNORECASE),
    re.compile(r"(?<![\w@])@[A-Za-z0-9_]{4,}"),
    re.compile(
        r"\b[a-z0-9.-]+\.(?:com|ru|me|net|org|io|app|xyz)\b",
        flags=re.IGNORECASE,
    ),
)

# Максимум matched_terms, попадающих в лог — чтобы не разрастался JSONB.
_MAX_LOGGED_TERMS = 10


@dataclass(frozen=True, slots=True)
class TextModerationResult:
    """Результат текстовой модерации.

    - `approved`/`decision` всегда согласованы: approved=True ⇔ decision='approved'.
    - `reason` — короткий код причины (`stop_word` / `link_detected`) для логики;
      пользовательский текст формируется на уровне хэндлера.
    - `matched_terms` — список совпавших токенов (для лога/админки/диагностики).
    """

    approved: bool
    decision: str  # 'approved' | 'rejected'
    reason: str | None
    matched_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ImageModerationResult:
    """Результат NSFW-проверки изображения.

    - `decision` — 'approved' | 'manual_review' | 'rejected'.
    - `nsfw_score` — вероятность NSFW в [0..1], либо None если модель
      недоступна / упала.
    - `reason` — короткий код (`model_unavailable`, `inference_error`,
      `nsfw_detected`) или None при approved.
    """

    decision: str
    nsfw_score: float | None
    reason: str | None


class ContentModerationService:
    """Текстовая модерация. Жёсткие моментальные решения, без ручного review.

    Стоп-слова грузятся из БД через `ModerationRepository.list_active_stop_words()`
    (с Redis-кэшем внутри репо). Хардкодить стоп-листы запрещено ().
    """

    def __init__(
        self,
        moderation_repo: ModerationRepository,
        settings_repo: SettingsRepository | None = None,
    ) -> None:
        self._moderation_repo = moderation_repo
        self._settings_repo = settings_repo

    async def check_text(
        self,
        text: str,
        *,
        allow_links: bool = False,
        target_kind: str,
        target_id: int | None = None,
        user_id: int | None = None,
    ) -> TextModerationResult:
        # Пустой ввод не имеет смысла проверять и логировать.
        if not text or not text.strip():
            return TextModerationResult(
                approved=True,
                decision="approved",
                reason=None,
                matched_terms=[],
            )

        normalized = normalize_for_moderation(text)
        # Лёгкая нормализация для ссылок: сохраняет `@`, `:`, `/`, цифры.
        link_text = normalize_for_link_detection(text)

        matched_terms: list[str] = []
        reason: str | None = None

        # 1. Стоп-слова из БД.
        stop_words = await self._moderation_repo.list_active_stop_words()
        for word in stop_words:
            pattern = word.pattern
            if not pattern:
                continue
            # При allow_links=True пропускаем стоп-слова с category='link' —
            # они дублируют встроенные проверки ссылок и должны игнорироваться.
            if allow_links and word.category == "link":
                continue
            if word.kind == "word":
                if re.search(
                    rf"\b{re.escape(pattern.lower())}\b",
                    normalized,
                    flags=re.UNICODE,
                ):
                    matched_terms.append(pattern)
                    if reason is None:
                        reason = "stop_word"
            elif word.kind == "regex":
                try:
                    compiled = re.compile(pattern, flags=re.IGNORECASE | re.UNICODE)
                except re.error as exc:
                    logger.warning(
                        "broken moderation regex id={} pattern={!r}: {}",
                        getattr(word, "id", None),
                        pattern,
                        exc,
                    )
                    continue
                # Link-regex'ы тестируем по «лёгкой» нормализации (там сохранены
                # @, :, /). Всё остальное — по полной.
                haystack = link_text if word.category == "link" else normalized
                if compiled.search(haystack):
                    matched_terms.append(pattern)
                    if reason is None:
                        reason = "link_detected" if word.category == "link" else "stop_word"
            # Неизвестный kind — молча пропускаем (CHECK-constraint в БД не пустит
            # такое значение, но на read-side оставляем мягким).

        # 2. Встроенная проверка ссылок (если не разрешены).
        if not allow_links:
            for link_re in _LINK_PATTERNS:
                link_match = link_re.search(link_text)
                if link_match is not None:
                    matched_terms.append(f"link:{link_match.group(0)}")
                    if reason is None or reason == "stop_word":
                        # Ссылка — более специфичная причина, поднимаем её.
                        reason = "link_detected"

        approved = not matched_terms
        decision = "approved" if approved else "rejected"

        await self._moderation_repo.log_moderation(
            user_id=user_id,
            target_kind=target_kind,
            target_id=target_id,
            check_type="text",
            decision=decision,
            reason=reason,
            matched_terms=matched_terms[:_MAX_LOGGED_TERMS] if matched_terms else None,
        )

        return TextModerationResult(
            approved=approved,
            decision=decision,
            reason=None if approved else reason,
            matched_terms=matched_terms,
        )

    async def check_image(
        self,
        image_bytes: bytes,
        *,
        target_kind: str,
        target_id: int | None = None,
        user_id: int | None = None,
    ) -> ImageModerationResult:
        """NSFW-проверка изображения.

        Аргументы:
            image_bytes: байты файла. Скачивание из Telegram — задача хэндлера.

        Поведение при недоступности модели — мягкий fallback на
        `manual_review` ().
        """
        detector = get_nudenet_detector()

        if not detector.is_available:
            decision = "manual_review"
            reason = "model_unavailable"
            await self._moderation_repo.log_moderation(
                user_id=user_id,
                target_kind=target_kind,
                target_id=target_id,
                check_type="nsfw_image",
                decision=decision,
                reason=reason,
                nsfw_score=None,
            )
            return ImageModerationResult(
                decision=decision,
                nsfw_score=None,
                reason=reason,
            )

        # ONNX-инференс синхронный и тяжёлый — не блокируем event loop.
        score = await asyncio.to_thread(detector.score, image_bytes)

        if score is None:
            decision = "manual_review"
            reason = "inference_error"
            await self._moderation_repo.log_moderation(
                user_id=user_id,
                target_kind=target_kind,
                target_id=target_id,
                check_type="nsfw_image",
                decision=decision,
                reason=reason,
                nsfw_score=None,
            )
            return ImageModerationResult(
                decision=decision,
                nsfw_score=None,
                reason=reason,
            )

        threshold = await self._resolve_threshold()

        if score < MANUAL_REVIEW_LOW_BOUND:
            decision = "approved"
            reason = None
        elif score < threshold:
            decision = "manual_review"
            reason = "nsfw_suspected"
        else:
            decision = "rejected"
            reason = "nsfw_detected"

        await self._moderation_repo.log_moderation(
            user_id=user_id,
            target_kind=target_kind,
            target_id=target_id,
            check_type="nsfw_image",
            decision=decision,
            reason=reason,
            nsfw_score=score,
        )

        return ImageModerationResult(
            decision=decision,
            nsfw_score=score,
            reason=reason,
        )

    async def _resolve_threshold(self) -> float:
        """Берём порог из app_settings (БД), fallback на env (`settings.nsfw_threshold`)."""
        if self._settings_repo is not None:
            try:
                value = await self._settings_repo.get_float("nsfw_threshold")
            except Exception as exc:
                logger.warning("Failed to read nsfw_threshold from settings: {}", exc)
                value = None
            if value is not None:
                return value
        return app_settings.nsfw_threshold
