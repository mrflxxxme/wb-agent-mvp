"""
SQLite-backed cache for Google Sheets data and alert deduplication.

Key design decisions:
- WAL mode + busy_timeout=5000 prevents "database is locked" errors
- Transactional writes (BEGIN IMMEDIATE): all sheets updated atomically or not at all
- alert_history persists across container restarts (Railway Volume mounted at data_dir)
- aiosqlite wraps sqlite3 in a background thread — never blocks the asyncio event loop
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import aiosqlite

from src.settings import settings

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Create tables and configure pragmas. Call once at startup."""
    os.makedirs(settings.data_dir, exist_ok=True)
    async with aiosqlite.connect(settings.db_path) as db:
        # Performance + concurrency
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")   # safe with WAL
        await db.execute("PRAGMA busy_timeout=5000")    # wait 5 s on lock

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sheet_cache (
                sheet_name TEXT PRIMARY KEY,
                data_json  TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                alert_key   TEXT PRIMARY KEY,
                fired_at    TEXT NOT NULL,
                resolved_at TEXT
            )
        """)
        await db.commit()
    logger.info("DB initialized at %s", settings.db_path)


# ── Sheet cache ────────────────────────────────────────────────────────────────

async def get_sheet(sheet_name: str) -> Optional[List[dict]]:
    """Return cached rows for a sheet, or None if not cached."""
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT data_json FROM sheet_cache WHERE sheet_name = ?", (sheet_name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
    return None


async def get_all_sheets() -> Dict[str, List[dict]]:
    """Return all cached sheets as a dict."""
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute("SELECT sheet_name, data_json FROM sheet_cache") as cursor:
            rows = await cursor.fetchall()
    return {name: json.loads(data) for name, data in rows}


async def set_all_sheets(data: Dict[str, List[dict]]) -> None:
    """
    Atomically replace ALL cached sheet data.
    Uses BEGIN IMMEDIATE to prevent readers seeing a half-written state.
    If any error occurs, old data is preserved (rollback).
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        try:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute("DELETE FROM sheet_cache")
            for name, rows in data.items():
                await db.execute(
                    "INSERT INTO sheet_cache (sheet_name, data_json, updated_at) VALUES (?, ?, ?)",
                    (name, json.dumps(rows, ensure_ascii=False), now),
                )
            await db.execute(
                "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('last_updated', ?)",
                (now,),
            )
            await db.commit()
            logger.debug("Cache updated: %d sheets at %s", len(data), now)
        except Exception:
            await db.rollback()
            raise


async def get_last_updated() -> Optional[datetime]:
    """Return the timestamp of the last successful cache refresh."""
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT value FROM cache_meta WHERE key = 'last_updated'"
        ) as cursor:
            row = await cursor.fetchone()
    if row:
        return datetime.fromisoformat(row[0])
    return None


async def is_stale() -> bool:
    """True if cache is older than CACHE_TTL_MINUTES or was never populated."""
    last = await get_last_updated()
    if last is None:
        return True
    age_minutes = (datetime.now(tz=timezone.utc) - last).total_seconds() / 60
    return age_minutes > settings.cache_ttl_minutes


# ── Alert deduplication ────────────────────────────────────────────────────────

async def is_alert_sent_today(alert_key: str) -> bool:
    """True if this alert was already fired today (date-based deduplication)."""
    today = date.today().isoformat()
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT fired_at FROM alert_history WHERE alert_key = ?", (alert_key,)
        ) as cursor:
            row = await cursor.fetchone()
    if row:
        fired_date = row[0][:10]  # "YYYY-MM-DD"
        return fired_date == today
    return False


async def record_alert(alert_key: str) -> None:
    """Record that an alert was sent now."""
    now = datetime.now(tz=timezone.utc).isoformat()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO alert_history (alert_key, fired_at, resolved_at) VALUES (?, ?, NULL)",
            (alert_key, now),
        )
        await db.commit()


async def resolve_alert(alert_key: str) -> None:
    """Mark an alert as resolved."""
    now = datetime.now(tz=timezone.utc).isoformat()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "UPDATE alert_history SET resolved_at = ? WHERE alert_key = ?",
            (now, alert_key),
        )
        await db.commit()
