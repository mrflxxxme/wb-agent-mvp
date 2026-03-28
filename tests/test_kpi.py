"""Unit tests for KPICalculator."""
import pytest
from datetime import date

from src.processing.kpi import KPICalculator, PeriodKPI, _safe_div


class TestSafeDiv:
    def test_normal_division(self):
        assert _safe_div(10.0, 5.0) == 2.0

    def test_zero_denominator_returns_none(self):
        assert _safe_div(10.0, 0.0) is None

    def test_none_numerator_returns_none(self):
        assert _safe_div(None, 5.0) is None

    def test_none_denominator_returns_none(self):
        assert _safe_div(10.0, None) is None

    def test_both_none_returns_none(self):
        assert _safe_div(None, None) is None


class TestKPICalculator:
    """Test KPICalculator.calculate() with synthetic data."""

    @pytest.fixture
    def sample_rows(self):
        return [
            {
                "date": "2026-03-20",
                "nm_id": "SKU001",
                "orders_sum_rub": 100_000,
                "orders_count": 50,
                "buyouts_sum_rub": 80_000,
                "adv_sum": 10_000,
                "marg_without_adv": 25.0,
                "marg_with_adv": 15.0,
                "profit_without_adv": 25_000,
                "profit_with_adv": 15_000,
                "buyout_percent_month": 80.0,
                "avg_position": 5.2,
                "organic_percent": 60.0,
                "add_to_cart_conversion": 8.5,
                "cart_to_order_conversion": 70.0,
                "promo_total_cost": 2_000,
                "promo_count": 1,
                "external_costs": 500,
                "stocks_enough_for_with_buyout_perc": 20,
                "views_search_auto": 1000,
                "clicks_search_auto": 50,
            },
            {
                "date": "2026-03-21",
                "nm_id": "SKU001",
                "orders_sum_rub": 120_000,
                "orders_count": 60,
                "buyouts_sum_rub": 95_000,
                "adv_sum": 15_000,
                "marg_without_adv": 23.0,
                "marg_with_adv": 10.5,
                "profit_without_adv": 27_600,
                "profit_with_adv": 12_600,
                "buyout_percent_month": 79.2,
                "avg_position": 4.8,
                "organic_percent": 55.0,
                "add_to_cart_conversion": 9.0,
                "cart_to_order_conversion": 68.0,
                "promo_total_cost": 0,
                "promo_count": 0,
                "external_costs": 0,
                "stocks_enough_for_with_buyout_perc": 18,
                "views_search_auto": 1200,
                "clicks_search_auto": 66,
            },
        ]

    def test_calculate_orders_sum(self, sample_rows):
        kpi = KPICalculator.calculate(sample_rows)
        assert kpi.orders_sum_rub == 220_000

    def test_calculate_orders_count(self, sample_rows):
        kpi = KPICalculator.calculate(sample_rows)
        assert kpi.orders_count == 110

    def test_calculate_adv_sum(self, sample_rows):
        kpi = KPICalculator.calculate(sample_rows)
        assert kpi.adv_sum == 25_000

    def test_drr_calculation(self, sample_rows):
        kpi = KPICalculator.calculate(sample_rows)
        expected = 25_000 / 220_000 * 100
        assert kpi.drr_percent == pytest.approx(expected, rel=0.01)

    def test_ctr_calculation(self, sample_rows):
        kpi = KPICalculator.calculate(sample_rows)
        total_views = 2200
        total_clicks = 116
        expected = total_clicks / total_views * 100
        assert kpi.ctr_search == pytest.approx(expected, rel=0.01)

    def test_stocks_uses_last_value(self, sample_rows):
        kpi = KPICalculator.calculate(sample_rows)
        assert kpi.stocks_enough_for_days == 18  # Last row

    def test_date_filtering(self, sample_rows):
        kpi = KPICalculator.calculate(
            sample_rows,
            date_from=date(2026, 3, 21),
            date_to=date(2026, 3, 21),
        )
        assert kpi.orders_sum_rub == 120_000

    def test_empty_rows_returns_empty_kpi(self):
        kpi = KPICalculator.calculate([])
        assert kpi.orders_sum_rub is None
        assert kpi.drr_percent is None

    def test_zero_orders_drr_is_none(self):
        rows = [{"date": "2026-03-20", "orders_sum_rub": 0, "adv_sum": 1000}]
        kpi = KPICalculator.calculate(rows)
        assert kpi.drr_percent is None  # Not ZeroDivisionError

    def test_none_values_in_rows_skipped(self):
        rows = [
            {"date": "2026-03-20", "orders_sum_rub": 100_000, "adv_sum": None},
            {"date": "2026-03-21", "orders_sum_rub": 50_000, "adv_sum": 5_000},
        ]
        kpi = KPICalculator.calculate(rows)
        assert kpi.orders_sum_rub == 150_000
        assert kpi.adv_sum == 5_000  # Only non-None value

    def test_compare_returns_wow_deltas(self, sample_rows):
        current = KPICalculator.calculate(sample_rows)
        # Fake previous period with half the orders
        prev_rows = [
            {**r, "orders_sum_rub": r["orders_sum_rub"] / 2}
            for r in sample_rows
        ]
        prev = KPICalculator.calculate(prev_rows)
        deltas = KPICalculator.compare(current, prev)
        assert deltas["orders_sum_rub"] == pytest.approx(100.0, rel=0.01)

    def test_compare_with_none_base_returns_none(self):
        current = PeriodKPI(orders_sum_rub=100_000)
        prev = PeriodKPI(orders_sum_rub=None)
        deltas = KPICalculator.compare(current, prev)
        assert deltas["orders_sum_rub"] is None
