"""
KPI calculation from raw Google Sheets rows.

All metrics are Optional[float] — division by zero returns None, not an exception.
This is critical: missing data should produce None, never crash the pipeline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PeriodKPI:
    """Aggregated KPIs for a time period (7 days, WoW, etc.)."""

    # Period metadata
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    days_count: int = 0

    # Revenue & Orders
    orders_sum_rub: Optional[float] = None
    orders_count: Optional[int] = None
    buyouts_sum_rub: Optional[float] = None

    # Advertising
    adv_sum: Optional[float] = None
    drr_percent: Optional[float] = None          # adv_sum / orders_sum * 100
    ctr_search: Optional[float] = None           # clicks / views * 100
    views_search_auto: Optional[float] = None
    clicks_search_auto: Optional[float] = None

    # Margins & Profitability
    marg_without_adv: Optional[float] = None     # % margin before advertising costs
    marg_with_adv: Optional[float] = None        # % margin after advertising costs
    profit_without_adv: Optional[float] = None   # absolute profit before adv
    profit_with_adv: Optional[float] = None      # absolute profit after adv

    # Stock
    stocks_enough_for_days: Optional[float] = None   # weighted average days of stock

    # Buyout quality
    buyout_percent_month: Optional[float] = None

    # Positioning & Conversion
    avg_position: Optional[float] = None
    organic_percent: Optional[float] = None
    add_to_cart_conversion: Optional[float] = None
    cart_to_order_conversion: Optional[float] = None

    # External costs
    promo_total_cost: Optional[float] = None
    promo_count: Optional[int] = None
    external_costs: Optional[float] = None

    # Plan execution (populated from РНП / plan_actual sheets)
    plan_execution_percent: Optional[float] = None
    plan_revenue: Optional[float] = None
    actual_revenue: Optional[float] = None


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Division that returns None instead of raising ZeroDivisionError."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _sum_col(rows: List[dict], col: str) -> Optional[float]:
    """Sum a numeric column, skipping empty/non-numeric values."""
    values = []
    for row in rows:
        val = row.get(col)
        if val is not None and val != "" and val != "-":
            try:
                values.append(float(str(val).replace(" ", "").replace(",", ".")))
            except (ValueError, TypeError):
                pass
    return sum(values) if values else None


def _avg_col(rows: List[dict], col: str) -> Optional[float]:
    """Average of a numeric column, skipping empty values."""
    values = []
    for row in rows:
        val = row.get(col)
        if val is not None and val != "" and val != "-":
            try:
                values.append(float(str(val).replace(" ", "").replace(",", ".")))
            except (ValueError, TypeError):
                pass
    return sum(values) / len(values) if values else None


def _last_col(rows: List[dict], col: str) -> Optional[float]:
    """Last non-empty value from a column (e.g., cumulative metrics)."""
    for row in reversed(rows):
        val = row.get(col)
        if val is not None and val != "" and val != "-":
            try:
                return float(str(val).replace(" ", "").replace(",", "."))
            except (ValueError, TypeError):
                pass
    return None


def _parse_date(val) -> Optional[date]:
    """Parse various date formats from Google Sheets cells."""
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(val), fmt).date()
        except ValueError:
            pass
    return None


def _filter_by_date(rows: List[dict], date_from: Optional[date], date_to: Optional[date]) -> List[dict]:
    """Filter rows to the specified date range using the 'date' column."""
    if date_from is None and date_to is None:
        return rows
    result = []
    for row in rows:
        d = _parse_date(row.get("date"))
        if d is None:
            continue
        if date_from and d < date_from:
            continue
        if date_to and d > date_to:
            continue
        result.append(row)
    return result


class KPICalculator:
    """Calculate PeriodKPI from raw checklist rows."""

    @staticmethod
    def calculate(
        rows: List[dict],
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> PeriodKPI:
        """
        Aggregate rows into a PeriodKPI.
        Rows should be from the 'checklist' sheet.
        """
        filtered = _filter_by_date(rows, date_from, date_to)
        if not filtered:
            logger.warning("No rows found for period %s – %s", date_from, date_to)
            return PeriodKPI(date_from=date_from, date_to=date_to)

        kpi = PeriodKPI(
            date_from=date_from,
            date_to=date_to,
            days_count=len(set(
                _parse_date(r.get("date")) for r in filtered if _parse_date(r.get("date"))
            )),
        )

        # Revenue & Orders
        kpi.orders_sum_rub = _sum_col(filtered, "orders_sum_rub")
        kpi.orders_count = int(_sum_col(filtered, "orders_count") or 0) or None
        kpi.buyouts_sum_rub = _sum_col(filtered, "buyouts_sum_rub")

        # Advertising
        kpi.adv_sum = _sum_col(filtered, "adv_sum")
        kpi.views_search_auto = _sum_col(filtered, "views_search_auto")
        kpi.clicks_search_auto = _sum_col(filtered, "clicks_search_auto")
        kpi.drr_percent = _safe_div(kpi.adv_sum, kpi.orders_sum_rub)
        if kpi.drr_percent is not None:
            kpi.drr_percent *= 100
        kpi.ctr_search = _safe_div(kpi.clicks_search_auto, kpi.views_search_auto)
        if kpi.ctr_search is not None:
            kpi.ctr_search *= 100

        # Margins (use averages — these are % values, not sums)
        kpi.marg_without_adv = _avg_col(filtered, "marg_without_adv")
        kpi.marg_with_adv = _avg_col(filtered, "marg_with_adv")

        # Profits (sums)
        kpi.profit_without_adv = _sum_col(filtered, "profit_without_adv")
        kpi.profit_with_adv = _sum_col(filtered, "profit_with_adv")

        # Stock (last value — represents current state)
        kpi.stocks_enough_for_days = _last_col(filtered, "stocks_enough_for_with_buyout_perc")

        # Buyout quality (last cumulative value)
        kpi.buyout_percent_month = _last_col(filtered, "buyout_percent_month")

        # Positioning (averages)
        kpi.avg_position = _avg_col(filtered, "avg_position")
        kpi.organic_percent = _avg_col(filtered, "organic_percent")

        # Conversions (averages)
        kpi.add_to_cart_conversion = _avg_col(filtered, "add_to_cart_conversion")
        kpi.cart_to_order_conversion = _avg_col(filtered, "cart_to_order_conversion")

        # External costs
        kpi.promo_total_cost = _sum_col(filtered, "promo_total_cost")
        kpi.promo_count = int(_sum_col(filtered, "promo_count") or 0) or None
        kpi.external_costs = _sum_col(filtered, "external_costs")

        return kpi

    @staticmethod
    def compare(current: PeriodKPI, previous: PeriodKPI) -> Dict[str, Optional[float]]:
        """
        Calculate WoW (or any period-over-period) percentage changes.
        Returns dict of metric_name → change_percent (positive = growth).
        None means comparison not possible (missing base or current data).
        """
        metrics = [
            "orders_sum_rub", "orders_count", "adv_sum", "drr_percent",
            "marg_with_adv", "profit_with_adv", "stocks_enough_for_days",
            "buyout_percent_month", "avg_position", "ctr_search",
            "add_to_cart_conversion", "cart_to_order_conversion",
        ]
        deltas: Dict[str, Optional[float]] = {}
        for m in metrics:
            cur = getattr(current, m, None)
            prev = getattr(previous, m, None)
            if cur is None or prev is None or prev == 0:
                deltas[m] = None
            else:
                deltas[m] = round((cur - prev) / abs(prev) * 100, 1)
        return deltas

    @staticmethod
    def enrich_from_plan(kpi: PeriodKPI, rnp_rows: List[dict]) -> PeriodKPI:
        """
        Populate plan_execution_percent from РНП sheet data.
        Looks for latest row with plan/fact columns.
        """
        for row in reversed(rnp_rows):
            plan = None
            fact = None
            for key in ["plan", "план", "План"]:
                if row.get(key) not in (None, "", "-"):
                    try:
                        plan = float(str(row[key]).replace(" ", "").replace(",", "."))
                        break
                    except ValueError:
                        pass
            for key in ["fact", "факт", "Факт"]:
                if row.get(key) not in (None, "", "-"):
                    try:
                        fact = float(str(row[key]).replace(" ", "").replace(",", "."))
                        break
                    except ValueError:
                        pass
            if plan and fact:
                kpi.plan_execution_percent = round(fact / plan * 100, 1)
                kpi.plan_revenue = plan
                kpi.actual_revenue = fact
                break
        return kpi
