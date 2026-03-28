"""
WB AI-Agent MVP — Entry point.

Startup sequence:
1. setup_logging()
2. start_health_server() — aiohttp on $PORT — FIRST, so Railway healthcheck passes
3. Settings validation (Pydantic — fail fast on missing env vars)
4. init_db() — SQLite WAL + schema
5. validate_startup() — probe Sheets + Gemini APIs
6. Build PTB Application with post_shutdown cleanup
7. Register handlers
8. Schedule jobs via PTB JobQueue (NO external AsyncIOScheduler)
9. run_polling()

IMPORTANT: src.* imports are deferred to inside async_main() so the health server
always starts even if Settings() raises ValidationError (missing env vars).
"""
from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web

logger = logging.getLogger(__name__)

_MSK = pytz.timezone("Europe/Moscow")
_UTC = pytz.utc


# ── Health check server ────────────────────────────────────────────────────────

async def health_handler(request: web.Request) -> web.Response:
    return web.Response(text="ok", content_type="text/plain")


async def start_health_server() -> None:
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health server started on port %d", port)


# ── Startup validation ─────────────────────────────────────────────────────────

async def validate_startup(reader: SheetsReader, gemini: GeminiClient) -> None:
    """Probe Sheets and Gemini APIs. Exit if Sheets is unreachable."""
    loop = asyncio.get_running_loop()

    # Sheets probe (critical — bot is useless without data)
    try:
        title = await loop.run_in_executor(_sheets_executor, reader.probe)
        logger.info("Sheets API: OK — spreadsheet '%s'", title)
    except Exception as e:
        logger.critical("Cannot connect to Google Sheets: %s", e)
        raise SystemExit(f"Google Sheets unreachable: {e}") from e

    # Gemini probe (warning only — may recover, alerts still work without AI)
    if await gemini.probe():
        logger.info("Gemini API: OK")
    else:
        logger.warning("Gemini API probe failed — AI responses may not work on startup")


# ── Scheduled jobs ─────────────────────────────────────────────────────────────

def make_cache_refresh_job(reader: SheetsReader):
    async def cache_refresh_job(context) -> None:
        logger.debug("Scheduled: cache_refresh started")
        loop = asyncio.get_running_loop()
        try:
            new_data = await loop.run_in_executor(_sheets_executor, reader.read_all)
            await cache.set_all_sheets(new_data)
            logger.info("Cache refreshed: %d sheets", len(new_data))
        except Exception as e:
            logger.warning("Cache refresh failed (serving stale data): %s", e)
    return cache_refresh_job


def make_alert_check_job(checker: AnomalyChecker, app: Application):
    async def alert_check_job(context) -> None:
        logger.debug("Scheduled: alert_check started")
        try:
            all_sheets = await cache.get_all_sheets()
            checklist = all_sheets.get("checklist", [])
            if not checklist:
                return

            from src.processing.kpi import KPICalculator
            from datetime import date, timedelta
            today = date.today()
            kpi = KPICalculator.calculate(checklist, today - timedelta(days=7), today)
            anomalies = checker.check_all(kpi, checklist)

            for anomaly in anomalies:
                if not await cache.is_alert_sent_today(anomaly.alert_key):
                    text = (
                        f"{anomaly.emoji} *Алерт: {anomaly.metric}*\n"
                        f"{anomaly.message}\n"
                        f"💡 {anomaly.action}"
                    )
                    await context.bot.send_message(
                        chat_id=settings.owner_chat_id,
                        text=text,
                        parse_mode="Markdown",
                    )
                    await cache.record_alert(anomaly.alert_key)
                    logger.info("Alert sent: %s", anomaly.alert_key)
        except Exception as e:
            logger.error("Alert check failed: %s", e, exc_info=True)
    return alert_check_job


def make_daily_summary_job(ctx_builder: ContextBuilder, gemini: GeminiClient, app: Application):
    async def daily_summary_job(context) -> None:
        logger.info("Scheduled: daily_summary started")
        try:
            ctx = await ctx_builder.build("daily")
            text = await gemini.ask(ctx, "daily")
            for part in text.split("\n\n\n"):   # crude split for long messages
                if part.strip():
                    await context.bot.send_message(
                        chat_id=settings.owner_chat_id,
                        text=part,
                        parse_mode="Markdown",
                    )
        except Exception as e:
            logger.error("Daily summary failed: %s", e, exc_info=True)
            await context.bot.send_message(
                chat_id=settings.owner_chat_id,
                text=f"❌ Ошибка при формировании дневного отчёта: {e}",
            )
    return daily_summary_job


def make_weekly_analysis_job(ctx_builder: ContextBuilder, gemini: GeminiClient, app: Application):
    async def weekly_analysis_job(context) -> None:
        logger.info("Scheduled: weekly_analysis started")
        try:
            ctx = await ctx_builder.build("weekly")
            text = await gemini.ask(ctx, "weekly")
            for part in text.split("\n\n\n"):
                if part.strip():
                    await context.bot.send_message(
                        chat_id=settings.owner_chat_id,
                        text=part,
                        parse_mode="Markdown",
                    )
        except Exception as e:
            logger.error("Weekly analysis failed: %s", e, exc_info=True)
            await context.bot.send_message(
                chat_id=settings.owner_chat_id,
                text=f"❌ Ошибка при формировании недельного анализа: {e}",
            )
    return weekly_analysis_job


async def notify_owner(app: Application, message: str) -> None:
    """Send a system notification to the owner chat."""
    try:
        await app.bot.send_message(chat_id=settings.owner_chat_id, text=message)
    except Exception as e:
        logger.error("Failed to notify owner: %s", e)


# ── Main ────────────────────────────────────────────────────────────────────────

async def async_main() -> None:
    # 1. Health server FIRST — Railway polls /health before anything else.
    #    Must bind before any src.* import so it survives Settings() ValidationError.
    asyncio.create_task(start_health_server())
    await asyncio.sleep(0.3)   # allow TCPSite to bind the socket

    # 2. Deferred imports — Settings() may raise ValidationError if env vars missing.
    #    Happens AFTER health server is up, so Railway sees a live /health endpoint.
    import datetime
    import pytz
    from telegram.ext import Application
    from src.bot.handlers import register_handlers
    from src.gemini.client import GeminiClient
    from src.logging_config import setup_logging  # noqa: F401 (already called in __main__)
    from src.processing.anomaly import AnomalyChecker
    from src.processing.context import ContextBuilder
    from src.settings import settings
    from src.sheets.reader import SheetsReader, _sheets_executor
    from src.storage import cache

    _UTC = pytz.utc

    # 3. Initialize DB
    await cache.init_db()

    # 4. Initialize core services
    reader = SheetsReader(settings.google_credentials, settings.spreadsheet_id)
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_model)
    checker = AnomalyChecker()
    ctx_builder = ContextBuilder(checker)

    # 5. Validate API connectivity
    await validate_startup(reader, gemini)

    # 5. Initial cache load (best-effort)
    logger.info("Initial Sheets data load...")
    loop = asyncio.get_running_loop()
    try:
        initial_data = await loop.run_in_executor(_sheets_executor, reader.read_all)
        await cache.set_all_sheets(initial_data)
        logger.info("Initial load complete: %d sheets", len(initial_data))
    except Exception as e:
        logger.warning("Initial data load failed (will retry on schedule): %s", e)

    # 6. Build PTB Application
    async def post_shutdown(application: Application) -> None:
        _sheets_executor.shutdown(wait=False)
        logger.info("Shutdown: executor stopped")

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_shutdown(post_shutdown)
        .build()
    )

    # 7. Register handlers
    register_handlers(app, ctx_builder, gemini, checker, reader)

    # 8. Schedule jobs via PTB JobQueue
    # IMPORTANT: PTB has its own internal APScheduler — do NOT create AsyncIOScheduler externally
    jq = app.job_queue

    jq.run_repeating(
        make_cache_refresh_job(reader),
        interval=settings.cache_ttl_minutes * 60,
        name="cache_refresh",
        job_kwargs={"misfire_grace_time": 60},
    )
    jq.run_repeating(
        make_alert_check_job(checker, app),
        interval=600,   # Every 10 minutes
        name="alert_check",
        first=60,       # First run after 1 minute (allow initial cache to load)
        job_kwargs={"misfire_grace_time": 120},
    )

    msk_daily_time = datetime.time(
        settings.daily_report_hour_utc, 0, tzinfo=_UTC
    )
    jq.run_daily(
        make_daily_summary_job(ctx_builder, gemini, app),
        time=msk_daily_time,
        days=tuple(range(0, 5)),    # Mon–Fri
        name="daily_summary",
        job_kwargs={"misfire_grace_time": 300},
    )

    msk_weekly_time = datetime.time(
        settings.weekly_report_hour_utc, 30, tzinfo=_UTC
    )
    jq.run_daily(
        make_weekly_analysis_job(ctx_builder, gemini, app),
        time=msk_weekly_time,
        days=(settings.weekly_report_weekday,),
        name="weekly_analysis",
        job_kwargs={"misfire_grace_time": 300},
    )

    # 9. Scheduler error listener → notify owner on job failure
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED

    def _scheduler_error_listener(event) -> None:
        logger.error(
            "Scheduler job '%s' failed: %s",
            event.job_id,
            event.exception,
            exc_info=getattr(event, "traceback", None),
        )
        asyncio.run_coroutine_threadsafe(
            notify_owner(app, f"❌ Job `{event.job_id}` failed: {event.exception}"),
            asyncio.get_event_loop(),
        )

    jq.scheduler.add_listener(
        _scheduler_error_listener,
        EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )

    logger.info("Starting bot polling...")

    # 10. Run (blocks until SIGTERM/SIGINT)
    await app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    from src.logging_config import setup_logging
    setup_logging()
    asyncio.run(async_main())
