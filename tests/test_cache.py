"""Unit tests for SQLite cache layer."""
import asyncio
from datetime import datetime, timezone
import pytest
import pytest_asyncio

# These tests require aiosqlite; skip if not installed
pytest.importorskip("aiosqlite")
import aiosqlite


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "test_cache.db")


@pytest.fixture(autouse=True)
def override_settings(tmp_db_path, monkeypatch):
    """Override settings to use temp DB path."""
    from src import settings as settings_module
    monkeypatch.setattr(settings_module.settings, "data_dir", str(tmp_path := tmp_db_path.rsplit("/", 1)[0]))
    monkeypatch.setattr(settings_module.settings, "db_path", tmp_db_path)
    # Also patch the module-level DB_PATH in cache
    import src.storage.cache as cache_mod
    monkeypatch.setattr(cache_mod, "DB_PATH", tmp_db_path, raising=False)
    # Patch settings inside cache module
    monkeypatch.setattr(cache_mod.settings, "db_path", tmp_db_path)
    monkeypatch.setattr(cache_mod.settings, "data_dir", str(tmp_db_path.rsplit("/", 1)[0]))
    monkeypatch.setattr(cache_mod.settings, "cache_ttl_minutes", 5)


@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_db_path):
    import src.storage.cache as cache
    await cache.init_db()
    async with aiosqlite.connect(tmp_db_path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cur:
            tables = {row[0] for row in await cur.fetchall()}
    assert "sheet_cache" in tables
    assert "cache_meta" in tables
    assert "alert_history" in tables


@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_db_path):
    import src.storage.cache as cache
    await cache.init_db()
    async with aiosqlite.connect(tmp_db_path) as db:
        async with db.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
    assert row[0].lower() == "wal"


@pytest.mark.asyncio
async def test_set_and_get_all_sheets(tmp_db_path):
    import src.storage.cache as cache
    await cache.init_db()
    data = {
        "checklist": [{"date": "2026-03-20", "orders_sum_rub": 100000}],
        "opu": [{"date": "2026-03-20", "revenue": 200000}],
    }
    await cache.set_all_sheets(data)
    result = await cache.get_all_sheets()
    assert "checklist" in result
    assert result["checklist"][0]["orders_sum_rub"] == 100000


@pytest.mark.asyncio
async def test_set_all_sheets_is_atomic(tmp_db_path):
    """If set_all_sheets fails midway, old data should be preserved."""
    import src.storage.cache as cache
    await cache.init_db()
    original = {"checklist": [{"date": "2026-03-19", "orders_sum_rub": 50000}]}
    await cache.set_all_sheets(original)

    # Simulate failure by passing non-serializable data
    import json
    class Unserializable:
        pass

    bad_data = {"checklist": [Unserializable()]}
    with pytest.raises(Exception):
        await cache.set_all_sheets(bad_data)

    # Original data should still be there
    result = await cache.get_all_sheets()
    assert result["checklist"][0]["orders_sum_rub"] == 50000


@pytest.mark.asyncio
async def test_get_last_updated_initially_none(tmp_db_path):
    import src.storage.cache as cache
    await cache.init_db()
    result = await cache.get_last_updated()
    assert result is None


@pytest.mark.asyncio
async def test_get_last_updated_after_set(tmp_db_path):
    import src.storage.cache as cache
    await cache.init_db()
    await cache.set_all_sheets({"checklist": []})
    result = await cache.get_last_updated()
    assert result is not None
    assert isinstance(result, datetime)


@pytest.mark.asyncio
async def test_is_stale_when_no_data(tmp_db_path):
    import src.storage.cache as cache
    await cache.init_db()
    assert await cache.is_stale() is True


@pytest.mark.asyncio
async def test_is_not_stale_after_fresh_set(tmp_db_path):
    import src.storage.cache as cache
    await cache.init_db()
    await cache.set_all_sheets({"checklist": []})
    assert await cache.is_stale() is False


@pytest.mark.asyncio
async def test_alert_deduplication(tmp_db_path):
    import src.storage.cache as cache
    await cache.init_db()
    key = "drr_percent_SKU001_2026-03-28"

    assert not await cache.is_alert_sent_today(key)
    await cache.record_alert(key)
    assert await cache.is_alert_sent_today(key)


@pytest.mark.asyncio
async def test_different_alert_keys_independent(tmp_db_path):
    import src.storage.cache as cache
    await cache.init_db()
    key1 = "drr_percent_SKU001_2026-03-28"
    key2 = "stocks_SKU002_2026-03-28"

    await cache.record_alert(key1)
    assert await cache.is_alert_sent_today(key1)
    assert not await cache.is_alert_sent_today(key2)
