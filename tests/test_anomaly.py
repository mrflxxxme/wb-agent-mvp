"""Unit tests for AnomalyChecker."""
import pytest
from pathlib import Path
from unittest.mock import patch
import yaml
import io

from src.processing.anomaly import AnomalyChecker, AnomalyRule, Anomaly, _check_rule
from src.processing.kpi import PeriodKPI

# Minimal valid rules.yaml content for testing
MINIMAL_RULES_YAML = """
rules:
  - metric: stocks_enough_for_days
    condition: lt
    threshold: 7
    severity: critical
    message_template: "Остаток {sku}: {value:.0f} дн."
    action: "Поставка"
  - metric: drr_percent
    condition: gt
    threshold: 30
    severity: critical
    message_template: "DRR {sku}: {value:.1f}%"
    action: "Снизить ставки"
  - metric: marg_with_adv
    condition: lt
    threshold: 0
    severity: critical
    message_template: "Маржа {sku}: {value:.1f}%"
    action: "Остановить рекламу"
"""


@pytest.fixture
def checker(tmp_path):
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(MINIMAL_RULES_YAML, encoding="utf-8")
    return AnomalyChecker(rules_path=rules_file)


class TestAnomalyRule:
    def test_valid_rule_parses(self):
        rule = AnomalyRule(
            metric="drr_percent",
            condition="gt",
            threshold=30.0,
            severity="critical",
            message_template="DRR {sku}: {value:.1f}%",
            action="Снизить ставки",
        )
        assert rule.condition == "gt"
        assert rule.threshold == 30.0

    def test_invalid_condition_raises(self):
        with pytest.raises(Exception):
            AnomalyRule(
                metric="drr_percent",
                condition="eq",   # invalid
                threshold=30.0,
                severity="critical",
                message_template="test",
                action="test",
            )

    def test_invalid_severity_raises(self):
        with pytest.raises(Exception):
            AnomalyRule(
                metric="drr_percent",
                condition="gt",
                threshold=30.0,
                severity="urgent",  # invalid
                message_template="test",
                action="test",
            )


class TestCheckRule:
    @pytest.fixture
    def gt_rule(self):
        return AnomalyRule(
            metric="drr_percent", condition="gt", threshold=30.0,
            severity="critical", message_template="DRR {sku}: {value:.1f}%",
            action="action"
        )

    @pytest.fixture
    def lt_rule(self):
        return AnomalyRule(
            metric="stocks_enough_for_days", condition="lt", threshold=7.0,
            severity="critical", message_template="Остаток {sku}: {value:.0f} дн.",
            action="action"
        )

    def test_gt_triggered_above_threshold(self, gt_rule):
        anomaly = _check_rule(gt_rule, 35.0, "SKU001")
        assert anomaly is not None
        assert anomaly.severity == "critical"
        assert anomaly.value == 35.0

    def test_gt_not_triggered_at_threshold(self, gt_rule):
        assert _check_rule(gt_rule, 30.0, "SKU001") is None

    def test_gt_not_triggered_below_threshold(self, gt_rule):
        assert _check_rule(gt_rule, 25.0, "SKU001") is None

    def test_lt_triggered_below_threshold(self, lt_rule):
        anomaly = _check_rule(lt_rule, 5.0, "SKU002")
        assert anomaly is not None
        assert anomaly.sku == "SKU002"

    def test_lt_not_triggered_above_threshold(self, lt_rule):
        assert _check_rule(lt_rule, 10.0, "SKU002") is None

    def test_none_value_returns_none(self, gt_rule):
        assert _check_rule(gt_rule, None, "SKU001") is None


class TestAnomalyChecker:
    def test_loads_rules_from_yaml(self, checker):
        assert len(checker.rules) == 3

    def test_check_kpi_critical_stock(self, checker):
        kpi = PeriodKPI(stocks_enough_for_days=5.0)
        anomalies = checker.check_kpi(kpi)
        stock_anomaly = [a for a in anomalies if a.metric == "stocks_enough_for_days"]
        assert len(stock_anomaly) == 1
        assert stock_anomaly[0].severity == "critical"

    def test_check_kpi_no_anomaly_when_ok(self, checker):
        kpi = PeriodKPI(
            stocks_enough_for_days=30.0,
            drr_percent=15.0,
            marg_with_adv=20.0,
        )
        anomalies = checker.check_kpi(kpi)
        assert len(anomalies) == 0

    def test_check_kpi_critical_drr(self, checker):
        kpi = PeriodKPI(drr_percent=45.0)
        anomalies = checker.check_kpi(kpi)
        drr_anomaly = [a for a in anomalies if a.metric == "drr_percent"]
        assert len(drr_anomaly) == 1

    def test_check_per_sku_detects_low_stock(self, checker):
        rows = [
            {"nm_id": "SKU001", "stocks_enough_for_days": 3},
            {"nm_id": "SKU002", "stocks_enough_for_days": 30},
        ]
        anomalies = checker.check_per_sku(rows)
        assert any(a.sku == "SKU001" for a in anomalies)
        assert not any(a.sku == "SKU002" for a in anomalies)

    def test_alert_key_deduplication_in_check_all(self, checker):
        # Same metric on both KPI and per-SKU should not duplicate
        kpi = PeriodKPI(drr_percent=40.0, stocks_enough_for_days=5.0)
        rows = [{"nm_id": "overall", "drr_percent": 40.0}]
        anomalies = checker.check_all(kpi, rows)
        # Should not have duplicate alert_keys
        keys = [a.alert_key for a in anomalies]
        assert len(keys) == len(set(keys))

    def test_critical_sorted_before_warning(self, tmp_path):
        # Create rules with both severities
        rules_yaml = """
rules:
  - metric: stocks_enough_for_days
    condition: lt
    threshold: 14
    severity: warning
    message_template: "{sku} {value:.0f}"
    action: "a"
  - metric: drr_percent
    condition: gt
    threshold: 20
    severity: critical
    message_template: "{sku} {value:.1f}"
    action: "b"
"""
        rf = tmp_path / "r.yaml"
        rf.write_text(rules_yaml)
        c = AnomalyChecker(rules_path=rf)
        kpi = PeriodKPI(stocks_enough_for_days=10.0, drr_percent=25.0)
        anomalies = c.check_kpi(kpi)
        assert anomalies[0].severity == "critical"

    def test_invalid_yaml_raises_at_init(self, tmp_path):
        bad_yaml = """
rules:
  - metric: drr_percent
    condition: invalid_op
    threshold: 30
    severity: critical
    message_template: "test"
    action: "test"
"""
        rf = tmp_path / "bad.yaml"
        rf.write_text(bad_yaml)
        with pytest.raises(Exception):
            AnomalyChecker(rules_path=rf)
