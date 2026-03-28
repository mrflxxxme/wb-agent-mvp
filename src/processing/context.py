"""
ContextBuilder: assembles the JSON payload sent to Gemini.

Rules:
1. Required fields always present: current_kpi, wow_comparison, anomalies, today_date, data_timestamp
2. Conditional fields based on query_type
3. Auto-trim: if payload > 40K tokens → strip P2, then P1 data
4. data_freshness_warning included when cache is stale
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.processing.anomaly import Anomaly, AnomalyChecker
from src.processing.kpi import KPICalculator, PeriodKPI
from src import storage

logger = logging.getLogger(__name__)

# Approximate token limit for Gemini context (conservative)
MAX_TOKENS = 40_000
# Rough estimate: 4 chars ≈ 1 token
CHARS_PER_TOKEN = 4


def _estimate_tokens(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str)) // CHARS_PER_TOKEN


def _kpi_to_dict(kpi: Optional[PeriodKPI]) -> Optional[dict]:
    if kpi is None:
        return None
    return {
        k: v for k, v in kpi.__dict__.items()
        if v is not None and not k.startswith("_")
    }


def _anomalies_to_list(anomalies: List[Anomaly]) -> List[dict]:
    return [
        {
            "severity": a.severity,
            "metric": a.metric,
            "sku": a.sku,
            "message": a.message,
            "action": a.action,
            "value": a.value,
            "threshold": a.threshold,
        }
        for a in anomalies
    ]


class ContextBuilder:
    """Builds JSON context for Gemini based on query type."""

    def __init__(self, checker: AnomalyChecker) -> None:
        self._checker = checker

    async def build(
        self,
        query_type: str,
        question: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build context dict for the given query type.
        query_type: "daily" | "weekly" | "plan" | "stocks" | "ads" | "ask"
        """
        # Load all cached data
        all_sheets = await storage.cache.get_all_sheets()
        last_updated = await storage.cache.get_last_updated()
        stale = await storage.cache.is_stale()

        checklist = all_sheets.get("checklist", [])
        checklist_cross = all_sheets.get("checklist_cross", [])
        opu = all_sheets.get("opu", [])
        unit = all_sheets.get("unit", [])
        plan = all_sheets.get("plan_actual", [])
        rnp = all_sheets.get("rnp", [])
        config_sheet = all_sheets.get("config", [])

        # Calculate KPIs for last 7 days
        today = date.today()
        week_ago = today - timedelta(days=7)
        two_weeks_ago = today - timedelta(days=14)

        current_kpi = KPICalculator.calculate(checklist, week_ago, today)
        current_kpi = KPICalculator.enrich_from_plan(current_kpi, rnp)

        prev_kpi = KPICalculator.calculate(checklist, two_weeks_ago, week_ago)

        wow = KPICalculator.compare(current_kpi, prev_kpi)
        anomalies = self._checker.check_all(current_kpi, checklist)

        # ── Mandatory context ──────────────────────────────────────────────
        ctx: Dict[str, Any] = {
            "query_type": query_type,
            "today_date": today.isoformat(),
            "data_timestamp": last_updated.isoformat() if last_updated else "unknown",
            "current_kpi_7d": _kpi_to_dict(current_kpi),
            "wow_comparison": wow,
            "anomalies": _anomalies_to_list(anomalies),
            "anomaly_count": {
                "critical": sum(1 for a in anomalies if a.severity == "critical"),
                "warning": sum(1 for a in anomalies if a.severity == "warning"),
            },
        }

        if stale:
            age_minutes = (
                int((datetime.now(tz=timezone.utc) - last_updated).total_seconds() / 60)
                if last_updated else 999
            )
            ctx["data_freshness_warning"] = (
                f"⚠️ Данные устарели на {age_minutes} минут. "
                "Используй /refresh для обновления."
            )

        if question:
            ctx["user_question"] = question

        # ── Conditional context by query_type ─────────────────────────────
        if query_type == "daily":
            ctx["plan_execution"] = _kpi_to_dict(current_kpi)
            ctx["top_daily_rows"] = checklist[-7:] if checklist else []

        elif query_type == "weekly":
            ctx["weekly_dynamics"] = checklist_cross[-14:] if checklist_cross else []
            ctx["opu_last_14d"] = opu[-14:] if opu else []
            ctx["unit_economics"] = unit[:20] if unit else []

        elif query_type == "plan":
            ctx["plan_data"] = plan[:50] if plan else []
            ctx["rnp_data"] = rnp[:20] if rnp else []
            ctx["opu_month"] = opu[-30:] if opu else []

        elif query_type == "stocks":
            # All SKUs with stock data
            stock_rows = [
                r for r in checklist
                if r.get("stocks_enough_for_with_buyout_perc") not in (None, "", "-")
            ]
            ctx["sku_stock_data"] = stock_rows[-50:]

        elif query_type == "ads":
            ctx["ads_data"] = [
                r for r in checklist
                if r.get("adv_sum") not in (None, "", "-", 0)
            ][-30:]
            ctx["unit_economics"] = unit[:20] if unit else []

        elif query_type == "ask":
            # Maximum context: all P0 data
            ctx["checklist_recent"] = checklist[-21:]   # last 3 weeks
            ctx["checklist_cross"] = checklist_cross[-14:]
            ctx["opu_recent"] = opu[-14:]
            ctx["unit_economics"] = unit[:30]
            ctx["plan_data"] = plan[:30]
            ctx["rnp_data"] = rnp[:20]
            ctx["config"] = config_sheet[:5]
            # P1 data (if available in cache)
            all_data = all_sheets
            if "cards" in all_data:
                ctx["cards"] = all_data["cards"][:50]
            if "hypotheses" in all_data:
                ctx["hypotheses"] = all_data["hypotheses"][:20]
            if "razdachi" in all_data:
                ctx["razdachi_recent"] = all_data["razdachi"][-10:]

        # ── Auto-trim if too large ─────────────────────────────────────────
        ctx = self._trim_context(ctx)

        logger.debug(
            "Built context for '%s': ~%d tokens, %d anomalies",
            query_type, _estimate_tokens(ctx), len(anomalies)
        )
        return ctx

    def _trim_context(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Remove optional fields until context fits within token budget."""
        trim_candidates = [
            # P2-level: remove first
            "seo", "jam", "external_costs_data",
            # P1-level: remove if still too large
            "hypotheses", "razdachi_recent", "cards",
            # Trim long lists
            "checklist_recent", "opu_recent", "checklist_cross",
        ]
        for key in trim_candidates:
            if _estimate_tokens(ctx) <= MAX_TOKENS:
                break
            if key in ctx:
                del ctx[key]
                logger.debug("Trimmed '%s' from context to fit token budget", key)

        # Last resort: truncate long lists
        for key in ["sku_stock_data", "ads_data", "plan_data", "top_daily_rows"]:
            if _estimate_tokens(ctx) <= MAX_TOKENS:
                break
            if key in ctx and isinstance(ctx[key], list) and len(ctx[key]) > 10:
                ctx[key] = ctx[key][-10:]
                logger.debug("Truncated '%s' to last 10 rows", key)

        return ctx
