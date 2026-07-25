"""resolve_file_url: TTL-кэш не отдаёт протухший Telegram file_path.

Регресс-тест к проду 2026-07-25: кэш без TTL держал URL после часового окна
Telegram → картинки ленты/аллеи отдавали 404. Теперь по истечении TTL идёт
перерезолв через getFile.
"""

from __future__ import annotations

import pytest

from app.api import media


class _FakeFile:
    def __init__(self, file_path: str | None) -> None:
        self.file_path = file_path


class _FakeBot:
    """Считает вызовы get_file и отдаёт меняющийся file_path."""

    def __init__(self) -> None:
        self.calls = 0

    async def get_file(self, file_id: str) -> _FakeFile:
        self.calls += 1
        return _FakeFile(f"photos/file_{self.calls}")


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    media._url_cache.clear()
    fake = _FakeBot()
    monkeypatch.setattr(media, "_get_bot", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_none_and_empty_return_none(_reset_cache) -> None:
    assert await media.resolve_file_url(None) is None
    assert await media.resolve_file_url("") is None
    assert _reset_cache.calls == 0


@pytest.mark.asyncio
async def test_cached_within_ttl_no_second_getfile(_reset_cache, monkeypatch) -> None:
    monkeypatch.setattr(media.time, "monotonic", lambda: 1000.0)
    first = await media.resolve_file_url("fid")
    # Второй вызов в пределах TTL — из кэша, без нового getFile.
    monkeypatch.setattr(media.time, "monotonic", lambda: 1000.0 + media._URL_TTL_SECONDS - 1)
    second = await media.resolve_file_url("fid")
    assert first == second
    assert _reset_cache.calls == 1


@pytest.mark.asyncio
async def test_expired_url_is_re_resolved(_reset_cache, monkeypatch) -> None:
    """Ключ фикса: по истечении TTL URL перерезолвится (свежий file_path)."""
    monkeypatch.setattr(media.time, "monotonic", lambda: 1000.0)
    first = await media.resolve_file_url("fid")
    # Прошло больше TTL — старый URL протух, нужен новый getFile.
    monkeypatch.setattr(media.time, "monotonic", lambda: 1000.0 + media._URL_TTL_SECONDS + 1)
    second = await media.resolve_file_url("fid")
    assert _reset_cache.calls == 2
    assert first != second  # file_path обновился, а не отдан протухший из кэша


@pytest.mark.asyncio
async def test_ttl_below_telegram_hour_guarantee() -> None:
    """TTL строго меньше часа — иначе окно, где URL уже мёртв, а кэш живой."""
    assert media._URL_TTL_SECONDS < 3600


@pytest.mark.asyncio
async def test_getfile_error_returns_none(_reset_cache, monkeypatch) -> None:
    async def _boom(file_id: str):
        raise RuntimeError("network down")

    _reset_cache.get_file = _boom
    assert await media.resolve_file_url("fid") is None
