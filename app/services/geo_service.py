"""Сервис поиска и нормализации городов РФ.

Загружает датасет ``app/data/cities_ru.json`` один раз при первом обращении
(lazy singleton через ``functools.lru_cache``).  Публичный API — класс
:class:`GeoService`, доступный через :func:`get_geo_service`.

Нормализация для поиска намеренно **не** переиспользует
:func:`app.services.text_normalization.normalize_for_moderation` — у той другая
задача (анти-leet для стоп-листов).  Здесь нужна более лёгкая нормализация:
lower + «ё→е» + trim + срезание префиксов «г.» / «город».
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Путь к датасету — относительно этого файла, не от cwd.
# ---------------------------------------------------------------------------
_DATA_PATH: Path = Path(__file__).resolve().parent.parent / "data" / "cities_ru.json"

# ---------------------------------------------------------------------------
# Алиасы: нормализованное разговорное название → каноническое имя в датасете.
# Ключи уже в нормализованном виде (lower, «ё→е»).
# ---------------------------------------------------------------------------
ALIASES: dict[str, str] = {
    "питер": "Санкт-Петербург",
    "спб": "Санкт-Петербург",
    "санкт-петербург": "Санкт-Петербург",
    "петербург": "Санкт-Петербург",
    "мск": "Москва",
    "москва": "Москва",
    "екб": "Екатеринбург",
    "екат": "Екатеринбург",
    "екатеринбург": "Екатеринбург",
    "нск": "Новосибирск",
    "новосибирск": "Новосибирск",
    "нижний": "Нижний Новгород",
    "нижний новгород": "Нижний Новгород",
    # «ростов» оставлен без алиаса намеренно — он неоднозначен:
    # «Ростов» (Ярославская обл.) и «Ростов-на-Дону» (Ростовская обл.)
}

# ---------------------------------------------------------------------------
# Группы регионов-«пар»: города из всех регионов группы считаются соседями.
# ---------------------------------------------------------------------------
REGION_GROUPS: list[frozenset[str]] = [
    frozenset({"Москва", "Московская область"}),
    frozenset({"Санкт-Петербург", "Ленинградская область"}),
    frozenset({"Севастополь", "Крым"}),
]

# Сколько результатов максимум возвращать при substring/prefix-матче.
_MAX_SUBSTRING_RESULTS: int = 8

# Минимальное сходство для difflib fuzzy-матча.
_FUZZY_CUTOFF: float = 0.72

# Разбивка префиксов, которые срезаются перед нормализацией.
_PREFIX_RE = re.compile(r"^(г\.|город)\s*", flags=re.IGNORECASE)


@dataclass(frozen=True)
class CityEntry:
    """Запись о городе из датасета."""

    city: str
    region: str
    federal_district: str
    lat: float | None
    lon: float | None
    population: int


@dataclass(frozen=True)
class CityMatchResult:
    """Результат подбора городов с признаком уверенности.

    fuzzy=True — совпадения получены только difflib-фолбэком (опечатки,
    похожие названия). Такие варианты НЕЛЬЗЯ принимать молча: «Ташкент»
    fuzzy-матчится в «Тайшет» — юзер должен подтвердить кнопкой.
    """

    entries: list[CityEntry]
    fuzzy: bool


class GeoService:
    """Сервис подбора городов по пользовательскому вводу.

    Инстанцировать напрямую не нужно — используй :func:`get_geo_service`.
    """

    def __init__(self, entries: list[CityEntry]) -> None:
        self._entries: list[CityEntry] = entries

        # Индекс нормализованное-имя → список CityEntry (для точного совпадения).
        # Список потому, что теоретически могут быть города с одинаковым названием
        # в разных регионах (хотя в нашем датасете нет).
        self._by_norm: dict[str, list[CityEntry]] = {}
        for entry in entries:
            key = self.normalize(entry.city)
            self._by_norm.setdefault(key, []).append(entry)

        # Отсортированный список нормализованных имён — для prefix-scan.
        self._norm_names: list[str] = sorted(self._by_norm.keys())

    # ------------------------------------------------------------------
    # Нормализация
    # ------------------------------------------------------------------

    @staticmethod
    def normalize(name: str) -> str:
        """Привести название города к сравниваемой форме.

        Шаги: срезать префикс «г.»/«город», lower, «ё→е», схлопнуть пробелы,
        trim.  Намеренно облегчённая нормализация — только для поиска, не для
        модерации.
        """
        if not name:
            return ""
        s = _PREFIX_RE.sub("", name.strip())
        s = s.lower()
        s = s.replace("ё", "е")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    # ------------------------------------------------------------------
    # Основной поиск
    # ------------------------------------------------------------------

    def match(self, query: str) -> list[CityEntry]:
        """Подобрать города по пользовательскому вводу (без признака fuzzy).

        Обёртка над :meth:`match_detailed` для мест, где уверенность
        совпадения не важна. В UX-потоках выбора города использовать
        match_detailed — fuzzy-варианты нельзя сохранять без подтверждения.
        """
        return self.match_detailed(query).entries

    def match_detailed(self, query: str) -> CityMatchResult:
        """Подобрать города по пользовательскому вводу.

        Стратегия (каскад, первое совпадение прерывает цепь):
        1. Алиас → один результат по каноническому имени (fuzzy=False).
        2. Точное совпадение + prefix/substring совмещённо: собираем все города,
           у которых нормализованное имя равно запросу ИЛИ начинается с него, или
           содержит его как подстроку.  Если найдено ≥1 — возвращаем (до
           ``_MAX_SUBSTRING_RESULTS``), отсортированных по population убыв.
           Такой подход гарантирует, что «Ростов» (точное название + префикс
           «Ростов-на-Дону») вернёт оба города, а «Казань» (уникально) — один.
           fuzzy=False.
        3. Fuzzy через ``difflib.get_close_matches`` как последний фолбэк —
           fuzzy=True, хэндлеры обязаны спросить подтверждение.
        4. Пустой список (fuzzy=False).
        """
        if not query or not query.strip():
            return CityMatchResult(entries=[], fuzzy=False)

        norm = self.normalize(query)

        # --- 1. Алиас (проверяем до prefix-скана — алиасы короткие и однозначные) ---
        canonical = ALIASES.get(norm)
        if canonical:
            canon_norm = self.normalize(canonical)
            found = self._by_norm.get(canon_norm)
            if found:
                return CityMatchResult(entries=list(found), fuzzy=False)

        # --- 2. Точное совпадение + prefix/substring (объединены) ---
        substring_hits: list[CityEntry] = []
        for norm_name in self._norm_names:
            if norm_name == norm or norm_name.startswith(norm) or norm in norm_name:
                substring_hits.extend(self._by_norm[norm_name])
        if substring_hits:
            substring_hits.sort(key=lambda e: e.population, reverse=True)
            return CityMatchResult(entries=substring_hits[:_MAX_SUBSTRING_RESULTS], fuzzy=False)

        # --- 3. Fuzzy ---
        close = difflib.get_close_matches(
            norm, self._norm_names, n=_MAX_SUBSTRING_RESULTS, cutoff=_FUZZY_CUTOFF
        )
        if close:
            fuzzy_hits: list[CityEntry] = []
            for n_name in close:
                fuzzy_hits.extend(self._by_norm[n_name])
            fuzzy_hits.sort(key=lambda e: e.population, reverse=True)
            return CityMatchResult(entries=fuzzy_hits, fuzzy=True)

        return CityMatchResult(entries=[], fuzzy=False)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def get(self, city: str) -> CityEntry | None:
        """Точный поиск по каноническому названию (нормализованно).

        Возвращает первый результат (в датасете дублей нет).
        """
        results = self._by_norm.get(self.normalize(city))
        return results[0] if results else None

    def region_of(self, city: str) -> str | None:
        """Регион (субъект РФ) для города или ``None``, если город не найден."""
        entry = self.get(city)
        return entry.region if entry else None

    def neighbor_cities(self, city: str, *, exclude_self: bool = True) -> list[str]:
        """Все города того же региона (и регионов-«пар»).

        Параметр ``exclude_self`` — исключить ли сам переданный город из списка.
        Возвращает канонические имена, отсортированные по убыванию population.
        """
        entry = self.get(city)
        if entry is None:
            return []

        # Собираем все регионы, которые входят в одну группу с регионом города.
        target_regions: set[str] = {entry.region}
        for group in REGION_GROUPS:
            if entry.region in group:
                target_regions |= group

        neighbors: list[CityEntry] = []
        for e in self._entries:
            if e.region in target_regions:
                if exclude_self and e.city == entry.city:
                    continue
                neighbors.append(e)

        neighbors.sort(key=lambda e: e.population, reverse=True)
        return [e.city for e in neighbors]

    def is_known(self, city: str) -> bool:
        """Проверить, есть ли город в датасете (по нормализованному имени)."""
        return self.normalize(city) in self._by_norm


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_geo_service() -> GeoService:
    """Вернуть singleton ``GeoService``.

    Датасет грузится один раз при первом вызове.  При ошибке чтения/парсинга
    возвращается сервис с пустым датасетом — бот не падает (
    принцип мягкого фолбэка).
    """
    entries: list[CityEntry] = []
    try:
        raw = _DATA_PATH.read_text(encoding="utf-8")
        data: list[dict] = json.loads(raw)
        for item in data:
            entries.append(
                CityEntry(
                    city=item["city"],
                    region=item["region"],
                    federal_district=item["federal_district"],
                    lat=item.get("lat"),
                    lon=item.get("lon"),
                    population=int(item.get("population", 0)),
                )
            )
        logger.info("GeoService: loaded {} cities from {}", len(entries), _DATA_PATH)
    except FileNotFoundError:
        logger.error("GeoService: dataset not found at {} — running with empty dataset", _DATA_PATH)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.error("GeoService: failed to parse dataset {}: {} — empty dataset", _DATA_PATH, exc)

    return GeoService(entries)
