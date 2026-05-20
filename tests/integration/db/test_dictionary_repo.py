from __future__ import annotations

import pytest

from app.db.models.dictionaries import ComplaintReason, Gender
from app.db.repositories.dictionary_repo import DictionaryRepository


@pytest.mark.asyncio
async def test_list_active_genders_from_seed(db_session) -> None:
    """Seed-миграция d96deed7e5da заполняет полы и причины жалоб."""
    repo = DictionaryRepository(db_session)
    genders = await repo.list_active(Gender)
    codes = {g.code for g in genders}
    assert {"male", "female", "other"}.issubset(codes)
    # Проверяем порядок: sort_order, затем id.
    assert [g.code for g in genders] == sorted(
        [g.code for g in genders],
        key=lambda c: {"male": 1, "female": 2, "other": 3}[c],
    )


@pytest.mark.asyncio
async def test_get_by_code_returns_entity(db_session) -> None:
    repo = DictionaryRepository(db_session)
    male = await repo.get_by_code(Gender, "male")
    assert male is not None
    assert male.title == "Мужской"


@pytest.mark.asyncio
async def test_get_by_code_unknown_returns_none(db_session) -> None:
    repo = DictionaryRepository(db_session)
    assert await repo.get_by_code(ComplaintReason, "no_such_reason") is None


@pytest.mark.asyncio
async def test_list_active_complaint_reasons(db_session) -> None:
    repo = DictionaryRepository(db_session)
    reasons = await repo.list_active(ComplaintReason)
    assert len(reasons) == 5
    assert reasons[0].code == "spam"
