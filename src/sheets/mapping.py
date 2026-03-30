"""
Maps internal Python keys to exact Google Sheets tab names.

IMPORTANT: Tab names are case-sensitive and must match exactly what's in the spreadsheet.
Confirmed with client on 2026-03-28.
"""
from __future__ import annotations

# P0 — mandatory sheets (required for all bot functionality)
P0_SHEETS: dict[str, str] = {
    "checklist": "checklist",
    "checklist_cross": "checklist_cross",
    "opu": "ОПиУ",
    "unit": "UNIT",
    "plan_actual": "plan_actual",    # technical tab (permanent name, no monthly rename needed)
    "rnp": "РНП",
    "config": "config",
}

# P1 — important sheets (used for richer context in /ask)
P1_SHEETS: dict[str, str] = {
    "cards": "cards",
    "razdachi": "Раздачи",
    "hypotheses": "Гипотезы",
    "promotions": "Акции",                  # WB акции — нужны для вопросов о ценах и марже
    "fin_sku": "Фин отчет по SKU",          # Детализированный финансовый отчёт по SKU
}

# P2 — desirable (trimmed first if context limit approached)
P2_SHEETS: dict[str, str] = {
    "jam": "Джем",                          # Рекламные кластеры, CTR, CPC, потенциал прибыли
    "mp_conv": "mp_conv",
    "external_costs": "Внешние расходы",   # Блогеры, посевы, внешние бюджеты
    "seo": "SEO",                           # Кластеры, позиции, охват запросов
    "plan_season": "План сезона",           # Сезонные цели, поставки, новинки
    "nm_ref": "Справочный лист nmID",       # Справочник SKU с nmID и отслеживаемыми запросами
}

ALL_SHEETS: dict[str, str] = {**P0_SHEETS, **P1_SHEETS, **P2_SHEETS}
