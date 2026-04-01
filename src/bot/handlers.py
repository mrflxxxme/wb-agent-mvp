"""
Telegram bot command handlers.

All handlers:
1. Check access control (allowed_ids)
2. Send "typing" action while processing
3. Call ContextBuilder → GeminiClient
4. Split long responses and send all parts
5. Handle RetryError from Gemini gracefully
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Optional

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from tenacity import RetryError

from src.bot.formatter import format_anomaly_list, format_status, split_message
from src.gemini.client import GeminiClient
from src.processing.anomaly import AnomalyChecker
from src.processing.context import ContextBuilder
from src.settings import settings
from src import storage

logger = logging.getLogger(__name__)

# Bot start time for uptime calculation
_START_TIME = time.monotonic()


# ── Access control decorator ──────────────────────────────────────────────────

def require_access(handler: Callable) -> Callable:
    """Decorator: reject users not in TELEGRAM_ALLOWED_IDS."""
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, **kwargs) -> Any:
        user = update.effective_user
        if user is None or user.id not in settings.allowed_ids:
            if update.effective_message:
                await update.effective_message.reply_text("🚫 Доступ запрещён.")
            logger.warning("Unauthorized access attempt from user_id=%s", user.id if user else "?")
            return
        return await handler(update, context, **kwargs)
    return wrapper


# ── Helper ────────────────────────────────────────────────────────────────────

async def _send_ai_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ctx_builder: ContextBuilder,
    gemini: GeminiClient,
    query_type: str,
    question: Optional[str] = None,
) -> None:
    """Build context → call Gemini → send split response."""
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )
    try:
        ctx = await ctx_builder.build(query_type, question)
        text = await gemini.ask(ctx, query_type, question)
    except RetryError:
        text = "⏳ Сервис Gemini временно недоступен. Попробуйте через минуту."
    except Exception as e:
        logger.error("Unexpected error in AI handler: %s", e, exc_info=True)
        text = "❌ Произошла внутренняя ошибка. Попробуйте позже."

    for part in split_message(text):
        try:
            await update.effective_message.reply_text(part, parse_mode="Markdown")
        except Exception:
            await update.effective_message.reply_text(part)


# ── Command handlers ──────────────────────────────────────────────────────────

def make_handlers(
    ctx_builder: ContextBuilder,
    gemini: GeminiClient,
    checker: AnomalyChecker,
    reader,
) -> None:
    """Returns a factory closure — actual registration is done in register_handlers."""
    pass  # Logic is in register_handlers below


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or user.id not in settings.allowed_ids:
        await update.effective_message.reply_text("🚫 Доступ запрещён.")
        return
    stale = await storage.cache.is_stale()
    last = await storage.cache.get_last_updated()
    last_str = last.strftime("%d.%m.%Y %H:%M UTC") if last else "нет данных"
    status = "⚠️ Кэш устарел" if stale else "✅ Данные актуальны"
    await update.effective_message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"Я — WB AI-Agent для аналитики кабинета.\n\n"
        f"*Статус:* {status}\n"
        f"*Последнее обновление:* {last_str}\n\n"
        "Команды:\n"
        "/report — дневной отчёт\n"
        "/week — недельный анализ\n"
        "/plan — выполнение плана\n"
        "/stocks — остатки\n"
        "/ads — реклама\n"
        "/alerts — активные аномалии\n"
        "/ask [вопрос] — любой вопрос\n"
        "/status — состояние системы\n"
        "/refresh — обновить данные",
        parse_mode="Markdown",
    )


def register_handlers(
    app: Application,
    ctx_builder: ContextBuilder,
    gemini: GeminiClient,
    checker: AnomalyChecker,
    reader,
) -> None:
    """Register all command handlers on the Application."""

    @require_access
    async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_ai_response(update, context, ctx_builder, gemini, "daily")

    @require_access
    async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_ai_response(update, context, ctx_builder, gemini, "weekly")

    @require_access
    async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_ai_response(update, context, ctx_builder, gemini, "plan")

    @require_access
    async def cmd_stocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_ai_response(update, context, ctx_builder, gemini, "stocks")

    @require_access
    async def cmd_ads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_ai_response(update, context, ctx_builder, gemini, "ads")

    @require_access
    async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show active anomalies without calling AI."""
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        try:
            all_sheets = await storage.cache.get_all_sheets()
            checklist = all_sheets.get("checklist", [])
            from src.processing.kpi import KPICalculator
            from datetime import date, timedelta
            today = date.today()
            kpi = KPICalculator.calculate(checklist, today - timedelta(days=7), today)
            anomalies = checker.check_all(kpi, checklist)
            text = format_anomaly_list(anomalies)
        except Exception as e:
            logger.error("Error in /alerts: %s", e, exc_info=True)
            text = "❌ Не удалось получить данные об аномалиях."
        await update.effective_message.reply_text(text, parse_mode="Markdown")

    @require_access
    async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /ask [question] command."""
        text = update.effective_message.text or ""
        parts = text.split(maxsplit=1)
        question = parts[1].strip() if len(parts) > 1 else None
        if not question:
            await update.effective_message.reply_text(
                "Напиши вопрос после команды, например:\n/ask Мы идём в план?"
            )
            return
        await _send_ai_response(update, context, ctx_builder, gemini, "ask", question)

    @require_access
    async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Force cache refresh."""
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        msg = await update.effective_message.reply_text("🔄 Обновляю данные из Google Sheets...")
        try:
            loop = asyncio.get_running_loop()
            from src.sheets.reader import _sheets_executor
            new_data = await loop.run_in_executor(_sheets_executor, reader.read_all)
            await storage.cache.set_all_sheets(new_data)
            from src.storage.cache import get_last_updated
            last = await get_last_updated()
            last_str = last.strftime("%d.%m.%Y %H:%M UTC") if last else "?"
            await msg.edit_text(f"✅ Данные обновлены: {last_str}")
        except Exception as e:
            logger.error("Refresh failed: %s", e, exc_info=True)
            await msg.edit_text(f"❌ Ошибка при обновлении: {e}")

    @require_access
    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show system status."""
        from src.storage.cache import get_last_updated, is_stale
        last = await get_last_updated()
        stale = await is_stale()
        last_str = last.strftime("%d.%m.%Y %H:%M UTC") if last else "нет данных"
        all_sheets = await storage.cache.get_all_sheets()
        from src.processing.kpi import KPICalculator
        from src.processing.anomaly import AnomalyChecker as AC
        from datetime import date, timedelta
        today = date.today()
        try:
            checklist = all_sheets.get("checklist", [])
            kpi = KPICalculator.calculate(checklist, today - timedelta(days=7), today)
            anomalies = checker.check_all(kpi, checklist)
            counts = {
                "critical": sum(1 for a in anomalies if a.severity == "critical"),
                "warning": sum(1 for a in anomalies if a.severity == "warning"),
            }
        except Exception:
            counts = {"critical": 0, "warning": 0}

        uptime = int(time.monotonic() - _START_TIME)
        text = format_status(
            last_updated_str=last_str,
            anomaly_counts=counts,
            sheets_ok=not stale,
            uptime_seconds=uptime,
        )
        await update.effective_message.reply_text(text, parse_mode="Markdown")

    @require_access
    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle free-text messages as /ask questions."""
        question = update.effective_message.text
        if question and not question.startswith("/"):
            await _send_ai_response(update, context, ctx_builder, gemini, "ask", question)

    # Global error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Unhandled PTB exception", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "❌ Произошла внутренняя ошибка. Попробуйте позже."
                )
            except Exception:
                pass

    # Register all handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("stocks", cmd_stocks))
    app.add_handler(CommandHandler("ads", cmd_ads))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    logger.info("Registered %d command handlers", 10)
