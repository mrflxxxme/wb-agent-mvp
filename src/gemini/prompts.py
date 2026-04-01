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
            "Проведи детальный анализ эффективности рекламы на основе данных ниже.\n\n"
            "ОБЯЗАТЕЛЬНЫЕ ШАГИ АНАЛИЗА:\n"
            "1. РЕАЛЬНЫЙ DRR: если в контексте есть external_costs или real_drr_percent — "
            "покажи реальный DRR = (adv_sum + Σ external_costs) / orders_sum_rub × 100. "
            "Сравни с внутренним DRR. Укажи «скрытую нагрузку» в рублях и процентах.\n"
            "2. КЛАСТЕРНЫЙ АНАЛИЗ: для каждой строки jam_clusters — оцени CTR "
            "(норма ≥ 0.5%, предупреждение < 0.5%, критично < 0.3%), "
            "CPO = бюджет / заказы кластера, рентабельность. "
            "Выдели топ-3 лучших и топ-3 худших по ROI с конкретным действием.\n"
            "3. PER-SKU: сопоставь ads_data и unit_economics по nmID/SKU — "
            "для каждого SKU факт DRR vs max_drr. Отметь превышения и запас.\n"
            "4. ПЛАН VS ФАКТ: используй rnp_data — % выполнения плана по "
            "рекламным расходам и DRR. Где самые большие отклонения?\n"
            "5. КОНВЕРСИЯ: если есть mp_conv — сравни конверсию по типам размещения. "
            "Какой тип даёт лучший CPO?\n"
            "6. nmID РАСШИФРОВКА: если есть nm_ref — подставляй название товара "
            "рядом с nmID в jam_clusters и ads_data.\n\n"
            "Доступные источники данных:\n"
            "  - ads_data: строки чеклиста с ненулевым adv_sum (последние 50 дней×SKU)\n"
            "  - unit_economics: UNIT-экономика с max_drr, маржой, себестоимостью по SKU\n"
            "  - rnp_data: РНП — план vs факт по заказам, выкупам, DRR, прибыли\n"
            "  - jam_clusters: рекламные кластеры с CTR, CPC, CPM, потенциалом прибыли\n"
            "  - external_costs: внешние расходы (блогеры, посевы) — включать в DRR!\n"
            "  - nm_ref: справочник nmID → название товара и отслеживаемые запросы\n"
            "  - mp_conv: конверсия по типу рекламного размещения\n"
            "  - real_drr_percent: предвычисленный реальный DRR с внешними расходами\n"
            "  - cpo_rub: предвычисленный CPO с внешними расходами\n\n"
            "Строго придерживайся формата ответа из системного промпта.\n\n"
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
