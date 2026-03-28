"""
Anomaly detection against configurable thresholds.

Design:
- AnomalyRule: Pydantic model validates rules.yaml at startup (no silent YAML typos)
- alert_key is deterministic: "{metric}_{sku}_{today}" — enables daily deduplication
- AnomalyChecker checks both aggregate KPI and per-SKU rows
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel

from src.processing.kpi import PeriodKPI

logger = logging.getLogger(__name__)

RULES_PATH = Path(__file__).parent.parent.parent / "config" / "rules.yaml"


class AnomalyRule(BaseModel):
    """Pydantic model — validates each rule entry in rules.yaml."""
    metric: str
    condition: Literal["gt", "lt"]
    threshold: float
    severity: Literal["warning", "critical"]
    message_template: str
    action: str


@dataclass
class Anomaly:
    """A detected anomaly with full context for alerting."""
    metric: str
    severity: str           # "warning" | "critical"
    message: str
    action: str
    sku: str                # "all" for aggregate anomalies
    value: float
    threshold: float
    alert_key: str          # Deterministic key for dedup: "{metric}_{sku}_{date}"

    @property
    def emoji(self) -> str:
        return "🚨" if self.severity == "critical" else "⚠️"


def _make_alert_key(metric: str, sku: str) -> str:
    return f"{metric}_{sku}_{date.today().isoformat()}"


def _check_rule(rule: AnomalyRule, value: Optional[float], sku: str) -> Optional[Anomaly]:
    """Apply a single rule to a value. Returns Anomaly or None."""
    if value is None:
        return None
    triggered = (
        (rule.condition == "lt" and value < rule.threshold) or
        (rule.condition == "gt" and value > rule.threshold)
    )
    if not triggered:
        return None
    message = rule.message_template.format(
        sku=sku, value=value, threshold=rule.threshold
    )
    return Anomaly(
        metric=rule.metric,
        severity=rule.severity,
        message=message,
        action=rule.action,
        sku=sku,
        value=value,
        threshold=rule.threshold,
        alert_key=_make_alert_key(rule.metric, sku),
    )


class AnomalyChecker:
    """Checks KPI and per-SKU data against configurable rules."""

    def __init__(self, rules_path: Path = RULES_PATH) -> None:
        raw = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        # Pydantic validation — raises ValidationError at startup if yaml is malformed
        self.rules: List[AnomalyRule] = [AnomalyRule(**r) for r in raw["rules"]]
        logger.info("Loaded %d anomaly rules from %s", len(self.rules), rules_path)

    def check_kpi(self, kpi: PeriodKPI) -> List[Anomaly]:
        """Check aggregate KPI metrics against rules. SKU label = 'overall'."""
        anomalies: List[Anomaly] = []
        for rule in self.rules:
            value = getattr(kpi, rule.metric, None)
            anomaly = _check_rule(rule, value, sku="overall")
            if anomaly:
                anomalies.append(anomaly)
        # Sort: critical first
        return sorted(anomalies, key=lambda a: 0 if a.severity == "critical" else 1)

    def check_per_sku(self, checklist_rows: List[dict]) -> List[Anomaly]:
        """
        Check latest values per SKU (nm_id or vendor_code).
        Takes the most recent row per SKU.
        """
        # Group by nm_id, keep latest row
        latest: dict[str, dict] = {}
        for row in checklist_rows:
            nm_id = str(row.get("nm_id", row.get("sku", "unknown")))
            latest[nm_id] = row

        anomalies: List[Anomaly] = []
        for nm_id, row in latest.items():
            for rule in self.rules:
                raw_val = row.get(rule.metric)
                if raw_val in (None, "", "-"):
                    continue
                try:
                    value = float(str(raw_val).replace(" ", "").replace(",", "."))
                except (ValueError, TypeError):
                    continue
                anomaly = _check_rule(rule, value, sku=nm_id)
                if anomaly:
                    anomalies.append(anomaly)

        return sorted(anomalies, key=lambda a: (0 if a.severity == "critical" else 1, a.sku))

    def check_all(self, kpi: PeriodKPI, checklist_rows: List[dict]) -> List[Anomaly]:
        """Combined check: aggregate KPI + per-SKU rows, deduplicated by alert_key."""
        seen: set[str] = set()
        result: List[Anomaly] = []
        for a in self.check_kpi(kpi) + self.check_per_sku(checklist_rows):
            if a.alert_key not in seen:
                seen.add(a.alert_key)
                result.append(a)
        return result
