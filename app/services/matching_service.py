"""Сервис мэтчинга: отбор кандидатов и скоринг по совместимости.

Алгоритм (промпт 4.1):
1. Жёсткая фильтрация в SQL (`MatchingRepository.find_candidates`): пол, возраст,
   активность анкеты, исключённые пользователи (лайки/дизлайки/блоки/просмотры
   за last `view_cooldown_days` дней).
   Добавлена каскадная фильтрация по городу (Stage 1 → Stage 2 → Stage 3 global)
   и хард-фильтр по вайбу (если searcher.desired_vibe_id IS NOT NULL).
   На Stage 2/3 (выход за пределы своего города) дополнительно применяется
   квалифицированный fallback по фандомам: оставляем только тех, у кого хоть
   один фандом из моих desired_fandoms. Stage 1 (свой город) фандомы не
   фильтрует — внутри города релевантность поддерживается локальностью.
2. Скоринг в Python: для топа кандидатов (до 200) суммируется взвешенный вклад
   фандомов, желаемых фандомов, интересов и совпадения вайбов + recency-бонус.
3. Веса читаются из `app_settings` через `SettingsRepository`. При отсутствии
   ключа — берём дефолт (см. `_DEFAULT_WEIGHTS`).
4. Возвращается топ-N `CandidateResult`, отсортированный по убыванию score, при
   равенстве — по `created_at` DESC. Каждый элемент несёт флаги близости города
   (from_neighbor_city, from_other_region) для отображения бейджей в хэндлере.

Сервис чистый: НЕ пишет `viewed_profiles` и НЕ логирует аналитику. Эти побочные
эффекты живут в хэндлере при фактическом показе анкеты (промпт 4.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.matching import Like, Match
from app.db.models.profile import Profile
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.settings_repo import (
    DEFAULT_LIKE_DAILY_LIMIT,
    SETTING_LIKE_DAILY_LIMIT,
    SettingsRepository,
)
from app.db.repositories.user_repo import UserRepository
from app.services.access import has_premium_access
from app.services.geo_service import get_geo_service

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from app.db.models.user import User

# Ключи в `app_settings`. Заведены в seed-миграции d96deed7e5da и 83faedaaca90.
SETTING_W_FANDOM = "match_w_fandom"
SETTING_W_VIBE = "match_w_vibe"
SETTING_W_DESIRED_FANDOM = "match_w_desired_fandom"
SETTING_W_INTEREST = "match_w_interest"
SETTING_W_RECENCY = "match_w_recency"
SETTING_VIEW_COOLDOWN_DAYS = "view_cooldown_days"

DEFAULT_VIEW_COOLDOWN_DAYS = 2
DEFAULT_CANDIDATE_POOL = 200

# TTL Redis-счётчика дневных лайков. Запас 48 часов — чтобы покрыть смену
# часовых поясов и не зависеть от точного "обнуления в полночь UTC".
LIKE_DAILY_COUNTER_TTL_SECONDS = 60 * 60 * 48


@dataclass(frozen=True, slots=True)
class MatchingWeights:
    """Веса слагаемых скоринг-функции. Все значения умножаются на
    соответствующий счётчик и суммируются."""

    w_fandom: float = 3.0
    w_vibe: float = 4.0
    w_desired_fandom: float = 2.0
    w_interest: float = 1.0
    w_recency: float = 1.0


_DEFAULT_WEIGHTS = MatchingWeights()


@dataclass(frozen=True, slots=True)
class CandidateRelations:
    """Предзагруженные множества M2M-связей анкеты — чтобы скоринг не делал N+1."""

    fandom_ids: frozenset[int] = field(default_factory=frozenset)
    desired_fandom_ids: frozenset[int] = field(default_factory=frozenset)
    interest_ids: frozenset[int] = field(default_factory=frozenset)
    desired_vibe_ids: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class LikeOutcome:
    """Результат `MatchingService.process_like`.

    Поля:
    * `like_recorded` — True, если новая запись Like создана; False — если дубликат
      ИЛИ если сработал дневной лимит лайков (см. `daily_limit_reached`).
    * `match_created` — True, если в результате (или ранее) встречного лайка возник Match.
    * `match_id` — id созданного Match (или существующего после race).
    * `other_user_telegram_id` — telegram_id собеседника, для уведомлений из хэндлера.
    * `other_user_id` — внутренний User.id собеседника.
    * `initial_message` — текст приветственного сообщения (если был superlike).
    * `daily_limit_reached` — True, если попытка лайка отклонена из-за исчерпания
      дневного лимита (`like_daily_limit`). Premium-доступ снимает лимит. Когда
      флаг True — Like в БД НЕ записан и Redis-счётчик не инкрементирован.
    """

    like_recorded: bool
    match_created: bool
    match_id: int | None
    other_user_telegram_id: int | None
    other_user_id: int | None
    initial_message: str | None
    daily_limit_reached: bool = False


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Результат скоринга одной анкеты. `breakdown` — для отладки и админки."""

    profile_id: int
    user_id: int
    score: float
    breakdown: dict[str, float]


@dataclass(frozen=True, slots=True)
class CandidateResult:
    """Кандидат с Profile-объектом и флагами близости города.

    Поля:
    * `profile` — ORM-объект анкеты.
    * `from_neighbor_city` — True, если кандидат из соседнего города того же
      региона (Stage 2 каскада). False для своего города и глобальной выдачи.
    * `from_other_region` — True, если кандидат из произвольного города за пределами
      своего региона (Stage 3 / global). False для Stage 1 и Stage 2.

    Инварианты: `from_neighbor_city` и `from_other_region` не могут быть оба True
    одновременно. Оба False → кандидат из того же города (Stage 1) или city IS NULL.
    """

    profile: Profile
    from_neighbor_city: bool = False
    from_other_region: bool = False


def _vibe_match_points(
    my_own_vibe_id: int | None,
    my_desired_vibe_ids: frozenset[int],
    their_own_vibe_id: int,
    their_desired_vibe_ids: frozenset[int],
) -> int:
    """0/2/4 — собственная шкала vibe_match до умножения на w_vibe.

    Двустороннее совпадение (мой own ∈ их desired И их own ∈ моих desired) = 4.
    Одностороннее = 2. Иначе 0.

    Пустой `desired_vibe_ids` означает «любой вайб» — соответствующая сторона
    считается несовпавшей (вклад 0 с этой стороны).
    """
    a = bool(their_desired_vibe_ids) and my_own_vibe_id in their_desired_vibe_ids
    b = bool(my_desired_vibe_ids) and their_own_vibe_id in my_desired_vibe_ids
    if a and b:
        return 4
    if a or b:
        return 2
    return 0


def _score_candidate(
    *,
    my_profile: Profile,
    my_relations: CandidateRelations,
    their_profile: Profile,
    their_relations: CandidateRelations,
    weights: MatchingWeights,
    now: datetime,
) -> CandidateScore:
    """Считает score одного кандидата. Чистая функция — удобно тестировать без БД."""
    fandom_overlap = len(my_relations.fandom_ids & their_relations.fandom_ids)
    desired_fandom_overlap = len(my_relations.desired_fandom_ids & their_relations.fandom_ids)
    interest_overlap = len(my_relations.interest_ids & their_relations.interest_ids)

    vibe_points = _vibe_match_points(
        my_profile.own_vibe_id,
        my_relations.desired_vibe_ids,
        their_profile.own_vibe_id,
        their_relations.desired_vibe_ids,
    )

    created_at = their_profile.created_at
    # created_at в БД timezone-aware (TIMESTAMPTZ). Подстрахуемся для тестовых
    # двойников, где могут передать naive datetime.
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    days_since = max(0.0, (now - created_at).total_seconds() / 86400.0)
    recency_factor = 1.0 / (days_since + 1.0)

    fandom_contrib = weights.w_fandom * fandom_overlap
    vibe_contrib = weights.w_vibe * vibe_points
    desired_contrib = weights.w_desired_fandom * desired_fandom_overlap
    interest_contrib = weights.w_interest * interest_overlap
    recency_contrib = weights.w_recency * recency_factor

    total = fandom_contrib + vibe_contrib + desired_contrib + interest_contrib + recency_contrib

    return CandidateScore(
        profile_id=their_profile.id,
        user_id=their_profile.user_id,
        score=total,
        breakdown={
            "fandom": fandom_contrib,
            "vibe": vibe_contrib,
            "desired_fandom": desired_contrib,
            "interest": interest_contrib,
            "recency": recency_contrib,
        },
    )


class MatchingService:
    """Подбор кандидатов для просмотра.

    Зависимости:
    * `ProfileRepository` — загрузить мою анкету и мои M2M-наборы.
    * `MatchingRepository` — фильтрация в SQL + предзагрузка M2M-связей кандидатов.
    * `SettingsRepository` — веса и cooldown из `app_settings` (с Redis-кэшем).
    * `DictionaryRepository` — зарезервировано на будущее (lookup-ы справочников).
    """

    def __init__(
        self,
        profile_repo: ProfileRepository,
        matching_repo: MatchingRepository,
        settings_repo: SettingsRepository,
        dictionary_repo: DictionaryRepository,
        user_repo: UserRepository | None = None,
        session: AsyncSession | None = None,
        redis: Redis | None = None,
    ) -> None:
        self._profile_repo = profile_repo
        self._matching_repo = matching_repo
        self._settings_repo = settings_repo
        # Зарезервировано для будущих фич (например, фильтр по справочнику).
        self._dictionary_repo = dictionary_repo
        # user_repo/session нужны только для `process_like`. Для `get_next_candidates`
        # их можно не передавать (обратная совместимость со старыми вызовами).
        self._user_repo = user_repo
        self._session = session
        # Redis нужен только для проверки дневного лимита лайков в `process_like`.
        # Если None — лимит не проверяется (обратная совместимость для старых
        # вызовов и юнит-тестов).
        self._redis = redis

    async def _load_weights(self) -> MatchingWeights:
        """Читает веса из app_settings; для отсутствующих ключей — дефолты."""

        async def _get(key: str, default: float) -> float:
            value = await self._settings_repo.get_float(key)
            return default if value is None else value

        return MatchingWeights(
            w_fandom=await _get(SETTING_W_FANDOM, _DEFAULT_WEIGHTS.w_fandom),
            w_vibe=await _get(SETTING_W_VIBE, _DEFAULT_WEIGHTS.w_vibe),
            w_desired_fandom=await _get(
                SETTING_W_DESIRED_FANDOM, _DEFAULT_WEIGHTS.w_desired_fandom
            ),
            w_interest=await _get(SETTING_W_INTEREST, _DEFAULT_WEIGHTS.w_interest),
            w_recency=await _get(SETTING_W_RECENCY, _DEFAULT_WEIGHTS.w_recency),
        )

    async def _load_view_cooldown_days(self) -> int:
        value = await self._settings_repo.get_int(SETTING_VIEW_COOLDOWN_DAYS)
        return DEFAULT_VIEW_COOLDOWN_DAYS if value is None else value

    async def get_next_candidates(self, user_id: int, *, limit: int = 20) -> list[CandidateResult]:
        """Возвращает топ-`limit` анкет для просмотра, отсортированных по score.

        Результат — список `CandidateResult`, каждый несёт флаги близости города:
        * `from_neighbor_city=True` — кандидат из соседнего города (Stage 2).
        * `from_other_region=True`  — кандидат из произвольного города (Stage 3 global).
        * Оба False → кандидат из того же города (Stage 1) или city IS NULL.

        Если у пользователя ещё нет анкеты — возвращается пустой список
        (UX-предпочтение: хэндлер сам решит, что показать).
        """
        my_profile = await self._profile_repo.get_by_user_id(user_id)
        if my_profile is None:
            return []

        my_looking_for_gender_ids = await self._profile_repo.get_looking_for_gender_ids(
            my_profile.id
        )
        if not my_looking_for_gender_ids:
            # Без указанных предпочтений по полу хард-фильтр всегда вернёт пусто —
            # вместо запроса с `IN ()` отдадим список напрямую.
            return []

        cooldown_days = await self._load_view_cooldown_days()
        excluded = await self._matching_repo.get_excluded_user_ids(
            user_id, view_cooldown_days=cooldown_days
        )

        my_desired_vibe_ids: frozenset[int] = frozenset(
            await self._profile_repo.get_desired_vibe_ids(my_profile.id)
        )
        my_desired_fandom_ids: frozenset[int] = frozenset(
            await self._profile_repo.get_desired_fandom_ids(my_profile.id)
        )

        candidates, from_neighbor_city, from_other_region = await self._fetch_candidates_cascade(
            my_profile=my_profile,
            my_looking_for_gender_ids=my_looking_for_gender_ids,
            excluded_user_ids=excluded,
            desired_vibe_ids=my_desired_vibe_ids,
            desired_fandom_ids=my_desired_fandom_ids,
        )

        if not candidates:
            return []

        # Один SQL-запрос на каждое отношение (4 запроса IN на весь батч) вместо
        # N+1 (по 4 запроса на каждого кандидата).
        relations_map = await self._matching_repo.load_candidates_with_relations(
            [c.id for c in candidates]
        )

        my_relations = CandidateRelations(
            fandom_ids=frozenset(await self._profile_repo.get_fandom_ids(my_profile.id)),
            desired_fandom_ids=my_desired_fandom_ids,
            interest_ids=frozenset(await self._profile_repo.get_interest_ids(my_profile.id)),
            desired_vibe_ids=my_desired_vibe_ids,
        )

        weights = await self._load_weights()
        now = datetime.now(tz=UTC)

        scored: list[tuple[CandidateScore, Profile]] = []
        for candidate in candidates:
            their_relations = relations_map.get(candidate.id, CandidateRelations())
            score = _score_candidate(
                my_profile=my_profile,
                my_relations=my_relations,
                their_profile=candidate,
                their_relations=their_relations,
                weights=weights,
                now=now,
            )
            scored.append((score, candidate))

        # Сортировка: score DESC, при равенстве — created_at DESC (свежее раньше).
        scored.sort(key=lambda item: (item[0].score, item[1].created_at), reverse=True)

        return [
            CandidateResult(
                profile=profile,
                from_neighbor_city=from_neighbor_city,
                from_other_region=from_other_region,
            )
            for _, profile in scored[:limit]
        ]

    async def _fetch_candidates_cascade(
        self,
        *,
        my_profile: Profile,
        my_looking_for_gender_ids: list[int],
        excluded_user_ids: set[int],
        desired_vibe_ids: frozenset[int],
        desired_fandom_ids: frozenset[int] = frozenset(),
    ) -> tuple[list[Profile], bool, bool]:
        """Каскадная выборка кандидатов по городу.

        Возвращает (candidates, from_neighbor_city, from_other_region):
        * Stage 1 — свой город: city_filter=[my_profile.city], оба флага False.
        * Stage 2 — соседние города региона: from_neighbor_city=True.
        * Stage 3 — глобальная выдача: from_other_region=True.
        * Если `my_profile.city IS NULL` — сразу Stage 3 (city IS NULL).

        Примечание: все кандидаты одного Stage несут одинаковые флаги. Это
        обоснованно: если пул включает и Stage-1 и Stage-2, мы никогда не
        попадём в эту ситуацию — только один Stage активен единовременно.

        Квалифицированный fallback: в Stage 2 и Stage 3 (выход за пределы
        своего города) дополнительно применяем хард-фильтр по
        `desired_fandom_ids` — оставляем только кандидатов, у которых хотя бы
        один фандом совпадает с моими desired. Stage 1 (свой город) этот
        фильтр НЕ применяет: локально мы готовы видеть всех. Если у юзера
        desired_fandom_ids пуст — фильтр выключен на всех стейджах.
        """
        common_kwargs: dict = dict(
            my_profile=my_profile,
            my_looking_for_gender_ids=my_looking_for_gender_ids,
            excluded_user_ids=excluded_user_ids,
            limit=DEFAULT_CANDIDATE_POOL,
            desired_vibe_ids=desired_vibe_ids,
        )

        # Хард-фильтр по фандомам активен только при выходе за свой город.
        # Stage 1 (свой город) фильтр не применяет — внутри города показываем
        # всех релевантных, фандомы остаются мягким скорингом.
        fandom_filter_outside = desired_fandom_ids if desired_fandom_ids else None

        my_city = my_profile.city

        if my_city is None:
            # city IS NULL → city-filter не применяем. Это «уже глобал» с точки
            # зрения каскада, поэтому применяем квалифицированный fallback по
            # фандомам, как для Stage 3.
            candidates = await self._matching_repo.find_candidates(
                **common_kwargs,
                city_filter=None,
                desired_fandom_ids=fandom_filter_outside,
            )
            logger.info(
                "matching cascade: city IS NULL → global, stage_returned=3, candidates_count={}",
                len(candidates),
            )
            return candidates, False, False

        # Stage 1: точное совпадение города. БЕЗ фильтра по фандомам.
        stage1 = await self._matching_repo.find_candidates(
            **common_kwargs,
            city_filter=[my_city],
            desired_fandom_ids=None,
        )
        if stage1:
            logger.info(
                "matching cascade: stage_returned=1, candidates_count={}, city={}",
                len(stage1),
                my_city,
            )
            return stage1, False, False

        # Stage 2: соседние города того же региона (через GeoService).
        # Включаем квалифицированный fallback по фандомам.
        geo = get_geo_service()
        neighbors = geo.neighbor_cities(my_city, exclude_self=True)
        if neighbors:
            stage2 = await self._matching_repo.find_candidates(
                **common_kwargs,
                city_filter=neighbors,
                desired_fandom_ids=fandom_filter_outside,
            )
            if stage2:
                logger.info(
                    "matching cascade: stage_returned=2, candidates_count={}, neighbors_count={}",
                    len(stage2),
                    len(neighbors),
                )
                return stage2, True, False

        # Stage 3: глобальная выдача — без фильтра по городу.
        # Включаем квалифицированный fallback по фандомам.
        stage3 = await self._matching_repo.find_candidates(
            **common_kwargs,
            city_filter=None,
            desired_fandom_ids=fandom_filter_outside,
        )
        logger.info(
            "matching cascade: stage_returned=3, candidates_count={}, desired_fandom_filter={}",
            len(stage3),
            bool(fandom_filter_outside),
        )
        return stage3, False, True

    # ------------------------- process_like (4.3) -------------------------

    def _pick_initial_message(
        self,
        *,
        my_kind: str,
        my_message: str | None,
        reciprocal: Like,
    ) -> str | None:
        """Выбирает текст приветственного сообщения для нового Match.

        Приоритет:
        * Если встречный лайк — superlike → берём его `message` (он был раньше).
        * Иначе если мой лайк — superlike → берём `my_message`.
        * Иначе None.

        То есть при двух superlike приоритет у того, кто поставил лайк первым
        (reciprocal — пришёл раньше моего).
        """
        if reciprocal.kind == "superlike" and reciprocal.message:
            return reciprocal.message
        if my_kind == "superlike" and my_message:
            return my_message
        return None

    async def _find_existing_match(self, user_a_id: int, user_b_id: int) -> Match | None:
        """Возвращает уже существующий Match между двумя пользователями (если есть)."""
        a, b = (user_a_id, user_b_id) if user_a_id < user_b_id else (user_b_id, user_a_id)
        for match in await self._matching_repo.list_matches_for_user(a):
            if match.user_a_id == a and match.user_b_id == b:
                return match
        return None

    @staticmethod
    def _like_quota_key(user_id: int, *, now: datetime | None = None) -> str:
        """Redis-ключ дневного счётчика лайков для пользователя.

        UTC-дата: переключение в 00:00 UTC. Берём дату «сегодня» один раз
        и используем для consistent чтения/инкремента.
        """
        moment = now if now is not None else datetime.now(tz=UTC)
        return f"likes:daily:{user_id}:{moment.date().isoformat()}"

    async def _load_like_daily_limit(self) -> int:
        """Читает значение `like_daily_limit` из app_settings, fallback на default."""
        value = await self._settings_repo.get_int(SETTING_LIKE_DAILY_LIMIT)
        return DEFAULT_LIKE_DAILY_LIMIT if value is None else value

    async def _check_and_increment_like_quota(
        self,
        *,
        from_user: User,
    ) -> bool:
        """Проверяет и инкрементирует дневной счётчик лайков.

        Возвращает True, если лайк можно записать; False — если лимит исчерпан.

        Premium-доступ короткозамыкает проверку (счётчик не трогается).
        Если Redis не сконфигурирован в сервисе или ошибка сети — лимит не
        действует (graceful degradation, fail-open для удобства тестов и
        чтобы временный отказ Redis не блокировал лайки в проде).
        """
        if self._redis is None:
            return True
        if has_premium_access(from_user):
            return True

        limit = await self._load_like_daily_limit()
        key = self._like_quota_key(from_user.id)
        # Атомарно: incr + expire через pipeline. Это устраняет окно потери TTL
        # (если процесс падал между incr и expire, ключ оставался навсегда).
        # expire применяем на каждый incr — это идемпотентная операция, лишний
        # RTT мы экономим за счёт pipeline.execute() в одном round-trip.
        try:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, LIKE_DAILY_COUNTER_TTL_SECONDS)
            results = await pipe.execute()
            count = int(results[0])
        except Exception as exc:
            logger.warning(
                "like quota: pipeline incr/expire failed for key={} — failing open: {}",
                key,
                exc,
            )
            return True
        if count > limit:
            # Превысили — компенсируем инкремент, чтобы счётчик не уехал
            # за лимит из-за неудачных попыток.
            try:
                await self._redis.decr(key)
            except Exception as exc:  # pragma: no cover — graceful
                logger.warning("like quota: decr (rollback) failed for key={}: {}", key, exc)
            logger.info(
                "like quota: user_id={} hit daily limit={} (count={})",
                from_user.id,
                limit,
                count,
            )
            return False
        return True

    async def process_like(
        self,
        *,
        from_user_id: int,
        to_user_id: int,
        kind: str = "like",
        message: str | None = None,
        from_user: User | None = None,
    ) -> LikeOutcome:
        """Записывает лайк и при необходимости создаёт мэтч.

        Логика:
        0. (Опционально, если переданы `from_user` и в конструктор передан
           `redis`.) Проверяем дневной лимит лайков `like_daily_limit` из
           app_settings. Premium-доступ снимает лимит. На превышении возвращаем
           `LikeOutcome(like_recorded=False, daily_limit_reached=True, ...)`
           БЕЗ записи Like и без расхода счётчика (декремент на откате).
        1. Пишем `Like` через SAVEPOINT. UNIQUE-конфликт → `like_recorded=False`,
           без падений; остальные поля результата — None.
        2. Если есть встречный лайк (`to_user` уже лайкнул `from_user`) — создаём
           `Match`, выбирая `initial_message` из superlike (приоритет — у того,
           кто поставил лайк первым).
        3. На случай гонки на UNIQUE(user_a, user_b) при `create_match` — ловим
           IntegrityError, откатываем savepoint и достаём уже существующий Match.
        4. Загружаем `other_user.telegram_id` через `user_repo` для возможных
           уведомлений из хэндлера. Сам сервис ничего не шлёт.
        """
        if self._session is None:
            raise RuntimeError(
                "MatchingService.process_like requires `session` in constructor",
            )

        # 0. Проверка дневного лимита лайков. Активна только если есть user+redis.
        if from_user is not None and self._redis is not None:
            quota_ok = await self._check_and_increment_like_quota(from_user=from_user)
            if not quota_ok:
                return LikeOutcome(
                    like_recorded=False,
                    match_created=False,
                    match_id=None,
                    other_user_telegram_id=None,
                    other_user_id=None,
                    initial_message=None,
                    daily_limit_reached=True,
                )

        # 1. Попытка записать Like.
        try:
            async with self._session.begin_nested():
                await self._matching_repo.add_like(
                    from_user_id=from_user_id,
                    to_user_id=to_user_id,
                    kind=kind,
                    message=message,
                )
        except IntegrityError as exc:
            logger.warning(
                "process_like: duplicate from_user_id={} to_user_id={} kind={}: {}",
                from_user_id,
                to_user_id,
                kind,
                exc,
            )
            # Дубликат Like (UNIQUE-конфликт) — не должен тратить дневную
            # квоту. Компенсируем инкремент, сделанный на шаге 0.
            if (
                from_user is not None
                and self._redis is not None
                and not has_premium_access(from_user)
            ):
                key = self._like_quota_key(from_user.id)
                try:
                    await self._redis.decr(key)
                except Exception as decr_exc:  # pragma: no cover — graceful
                    logger.warning(
                        "like quota: decr (duplicate rollback) failed for key={}: {}",
                        key,
                        decr_exc,
                    )
            return LikeOutcome(
                like_recorded=False,
                match_created=False,
                match_id=None,
                other_user_telegram_id=None,
                other_user_id=None,
                initial_message=None,
            )

        # 2. Проверяем взаимность.
        reciprocal = await self._matching_repo.has_reciprocal_like(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
        )

        match_id: int | None = None
        match_created = False
        initial_message: str | None = None
        if reciprocal is not None:
            initial_message = self._pick_initial_message(
                my_kind=kind,
                my_message=message,
                reciprocal=reciprocal,
            )
            try:
                async with self._session.begin_nested():
                    match = await self._matching_repo.create_match(
                        user_a_id=from_user_id,
                        user_b_id=to_user_id,
                        initial_message=initial_message,
                    )
                match_id = match.id
                match_created = True
            except IntegrityError as exc:
                # Гонка: параллельный лайк уже создал Match. Берём существующий.
                logger.warning(
                    "process_like: race on create_match from={} to={}: {}",
                    from_user_id,
                    to_user_id,
                    exc,
                )
                existing = await self._find_existing_match(from_user_id, to_user_id)
                match_id = existing.id if existing is not None else None
                match_created = False
                initial_message = existing.initial_message if existing is not None else None

        # 3. Загружаем telegram_id собеседника (для уведомлений из хэндлера).
        other_telegram_id: int | None = None
        if self._user_repo is not None:
            other_user = await self._user_repo.get_by_id(to_user_id)
            if other_user is not None:
                other_telegram_id = other_user.telegram_id

        return LikeOutcome(
            like_recorded=True,
            match_created=match_created,
            match_id=match_id,
            other_user_telegram_id=other_telegram_id,
            other_user_id=to_user_id if match_id is not None else None,
            initial_message=initial_message,
        )

    async def list_incoming_likes_for_user(self, user_id: int) -> list[Like]:
        """Лайки на меня, на которые я ещё не ответил (нет встречного Like/Dislike,
        нет Match). Thin-wrapper над `MatchingRepository.list_incoming_likes`."""
        return await self._matching_repo.list_incoming_likes(user_id)

    async def list_matches_for_user(self, user_id: int) -> list[Match]:
        """Мои мэтчи, отсортированные по created_at DESC.
        Thin-wrapper над `MatchingRepository.list_matches_for_user`."""
        return await self._matching_repo.list_matches_for_user(user_id)
