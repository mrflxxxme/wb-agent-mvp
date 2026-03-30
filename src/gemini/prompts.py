"""
Prompt templates for different query types.
Each template takes the JSON context dict and returns a formatted prompt string.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "system_prompt.md"
SYSTEM_PROMPT: str = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _ctx_json(ctx: Dict[str, Any]) -> str:
    return json.dumps(ctx, ensure_ascii=False, indent=2, default=str)


def build_prompt(
    context: Dict[str, Any],
    query_type: str,
    question: Optional[str] = None,
) -> str:
    """Build the user-turn prompt for Gemini based on query type."""

    if query_type == "daily":
        return (
            "Сделай ежедневный отчёт по кабинету WB на основе данных ниже.\n"
            "Сфокусируйся на: идём ли в план, топ-3 падений, критичные остатки, 3 действия на сегодня.\n\n"
            f"ДАННЫЕ:\n{_ctx_json(context)}"
        )

    elif query_type == "weekly":
        return (
            "Сделай еженедельный анализ кабинета WB на основе данных ниже.\n"
            "Сфокусируйся на: WoW динамика (кто вырос / упал), активные гипотезы, "
            "5 управленческих решений на неделю.\n\n"
            f"ДАННЫЕ:\n{_ctx_json(context)}"
        )

    elif query_type == "plan":
        return (
            "Проанализируй выполнение плана месяца на основе данных ниже.\n"
            "Сфокусируйся на: % выполнения, прогноз до конца месяца, топ-причины отставания / опережения.\n\n"
            f"ДАННЫЕ:\n{_ctx_json(context)}"
        )

    elif query_type == "stocks":
        return (
            "Проанализируй риски по остаткам товаров на основе данных ниже.\n"
            "Сфокусируйся на: какие SKU критичны (< 7 дней), какие на грани (< 14 дней), "
            "рекомендации по срочным поставкам.\n\n"
            f"ДАННЫЕ:\n{_ctx_json(context)}"
        )

    elif query_type == "ads":
        return (
            "Проанализируй эффективность рекламы на основе данных ниже.\n"
            "Сфокусируйся на: DRR по каждому SKU vs max_drr из UNIT-экономики, "
            "убыточные кампании, рекомендации по ставкам.\n\n"
            f"ДАННЫЕ:\n{_ctx_json(context)}"
        )

    else:  # "ask" or unknown
        q = question or "Дай общую диагностику кабинета."
        return (
            f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {q}\n\n"
            "Ответь исчерпывающе, используя ВСЕ релевантные данные из контекста ниже.\n"
            "Доступные источники данных:\n"
            "  - checklist_recent: дневная динамика SKU (трафик, заказы, выкупы, маржа, DRR)\n"
            "  - rnp_data: РНП — факт vs план по всем метрикам\n"
            "  - plan_data: план месяца и прогноз\n"
            "  - unit_economics: UNIT-экономика по каждому SKU\n"
            "  - opu_recent: финансовые итоги ОПиУ\n"
            "  - fin_report_sku: детализированный финотчёт по SKU\n"
            "  - hypotheses: гипотезы и эксперименты\n"
            "  - razdachi_recent: раздачи/самовыкупы (влияют на органику!)\n"
            "  - jam_clusters: рекламные кластеры с CTR/CPC/потенциалом\n"
            "  - external_costs: внешние расходы (влияют на DRR!)\n"
            "  - promotions: акции WB и маржа с/без акции\n"
            "  - seo_clusters: SEO-кластеры и позиции\n"
            "  - plan_season: план сезона и поставки\n\n"
            "Строго придерживайся формата ответа из системного промпта.\n\n"
            f"ДАННЫЕ:\n{_ctx_json(context)}"
        )
