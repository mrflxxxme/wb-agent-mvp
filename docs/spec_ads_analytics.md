# Spec: Специализация агента на анализе рекламы

**Статус:** Готово к реализации
**Версия:** 1.0
**Проект:** WB AI-Agent (Wildberries analytics Telegram bot)
**Стек:** Python, python-telegram-bot v21, google-genai (gemini-2.5-flash), gspread, Railway

---

## Проблема

Команда `/ads` — основная точка входа для рекламных вопросов — использует урезанный контекст:

```python
# src/processing/context.py, строки 148-153 (ТЕКУЩЕЕ СОСТОЯНИЕ — менять)
elif query_type == "ads":
    ctx["ads_data"] = [
        r for r in checklist
        if r.get("adv_sum") not in (None, "", "-", 0)
    ][-30:]
    ctx["unit_economics"] = unit[:20] if unit else []
```

Отсутствуют все рекламно-специфичные источники: `jam_clusters` (CTR, CPC, CPM, кластерный потенциал прибыли), `external_costs` (блогеры, посевы — напрямую влияют на реальный DRR), `rnp_data` (план vs факт), `nm_ref` (справочник nmID), `mp_conv` (конверсия по типу размещения). Промпт и системный промпт для `/ads` также поверхностны.

**Последствие:** агент не может дать ни кластерный анализ, ни расчёт реального DRR, ни оценку эффективности внешних бюджетов — ключевые задачи рекламной аналитики недостижимы без данных.

---

## Цели

1. `/ads` получает все рекламные источники данных и выдаёт кластерный анализ с конкретными цифрами по CTR/CPC/ROI
2. Реальный DRR (включая external_costs) рассчитывается и объясняется в каждом рекламном отчёте
3. Агент умеет связывать nmID из jam_clusters с SKU из checklist для per-SKU анализа
4. Аномальный CTR (ниже порога) автоматически попадает в `/alerts` без изменений кода обработчиков

## Не цели (явно вне скоупа)

- Новые Telegram-команды (`/ads_clusters`, `/ads_budget`) — `/ask` покрывает эти кейсы; новые хэндлеры не создавать
- Delta-аномалии (CTR упал на X% за день) — требуют рефактора `AnomalyChecker`; это LATER
- Автоматические push-алерты по рекламным событиям — отдельная задача LATER
- Оптимизация ставок на основе jam.cpc + unit.max_drr — LATER, после подтверждения схемы jam
- Хранение снэпшотов jam для трендов — LATER

---

## User Stories

**Как аналитик кабинета WB**, я хочу получить от `/ads` полный кластерный анализ — CTR, CPO, ROI по каждому кластеру из Джем — чтобы понять, какие кластеры прибыльны, а какие сжигают бюджет.

**Как аналитик**, я хочу видеть в `/ads` реальный DRR, включающий внешние расходы на блогеров и посевы, чтобы не принимать решения на основе заниженных цифр.

**Как аналитик**, я хочу чтобы `/ads` сравнивал фактический DRR по каждому SKU с `max_drr` из UNIT-экономики и явно сигнализировал о превышениях.

**Как аналитик**, я хочу получать `/alerts` когда CTR падает ниже порога — без дополнительных действий с моей стороны.

---

## Фазы реализации

---

## ФАЗА 1 — NOW (один коммит, три файла)

Все три изменения **независимы** и могут выполняться параллельно. Ни одно не создаёт новых файлов. Все изменяют только существующий код.

---

### Изменение 1: Обогащение контекста `/ads`

**Файл:** `src/processing/context.py`

**Приоритет:** P0 (без этого Фазы 2 и 3 не имеют смысла)

#### Что менять — блок `elif query_type == "ads":`

**Заменить строки 148–153 (включительно) на:**

```python
elif query_type == "ads":
    # Обязательные источники для рекламного анализа
    ctx["ads_data"] = [
        r for r in checklist
        if r.get("adv_sum") not in (None, "", "-", 0)
    ][-50:]
    ctx["unit_economics"] = unit[:20] if unit else []
    ctx["rnp_data"] = rnp[:20] if rnp else []
    if all_sheets.get("jam"):
        ctx["jam_clusters"] = all_sheets["jam"][:30]
    if all_sheets.get("external_costs"):
        ctx["external_costs"] = all_sheets["external_costs"][-10:]
    # Опциональные источники
    if all_sheets.get("nm_ref"):
        ctx["nm_ref"] = all_sheets["nm_ref"][:20]
    if all_sheets.get("mp_conv"):
        ctx["mp_conv"] = all_sheets["mp_conv"][:20]
```

**Критерии корректности:**
- `ads_data` увеличен с `[-30:]` до `[-50:]`
- `rnp_data` всегда добавляется (не опциональный)
- `jam_clusters` и `external_costs` добавляются через `if all_sheets.get(...):`
- `nm_ref` и `mp_conv` добавляются через `if all_sheets.get(...):`
- Никакого нового `try/except` — паттерн `if all_sheets.get(key):` уже является идиомой проекта

#### Что менять — метод `_trim_context`

**Заменить строки 196–203 (блок `trim_candidates`) на:**

```python
trim_candidates = [
    # P2-level: remove first (наименее критичные для любого запроса)
    "plan_season", "seo_clusters",
    # Рекламные P2 — удалять ПОСЛЕ seo и plan_season, НО ДО P1
    "mp_conv", "nm_ref", "external_costs",
    # P1-level
    "fin_report_sku", "promotions", "hypotheses", "razdachi_recent", "cards",
    # jam_clusters — самый ценный источник для /ads, удаляем последним среди P2
    "jam_clusters",
    # Trim long lists (P0)
    "checklist_recent", "opu_recent", "checklist_cross",
    # /ads specific
    "rnp_data",
]
```

**Почему именно такой порядок:**
- `jam_clusters` перемещается с 3-й позиции на предпоследнюю перед P0 — для `/ads` это самый ценный источник, его нельзя терять раньше P1-данных
- `mp_conv`, `nm_ref`, `external_costs` добавляются в список (иначе при превышении бюджета они никогда не удаляются)
- `rnp_data` добавляется в конец (удалять последним среди новых ключей)
- Порядок для остальных query_type не меняется (они не используют эти ключи)

**Критерии корректности:**
- Существующие ключи `plan_season`, `seo_clusters`, `fin_report_sku`, `promotions`, `hypotheses`, `razdachi_recent`, `cards`, `checklist_recent`, `opu_recent`, `checklist_cross` присутствуют в списке
- `jam_clusters` стоит ПОСЛЕ `external_costs` и ПОСЛЕ всех P1-ключей
- Метод `_trim_context` не получает параметров — он не знает о `query_type`, это нормально

---

### Изменение 2: Переписать промпт `/ads`

**Файл:** `src/gemini/prompts.py`

**Приоритет:** P0

#### Что менять

**Найти блок `elif query_type == "ads":` (строки ~48–54) и заменить целиком:**

```python
elif query_type == "ads":
    return (
        "Проведи детальный анализ эффективности рекламы на основе данных ниже.\n\n"
        "ОБЯЗАТЕЛЬНЫЕ ШАГИ АНАЛИЗА:\n"
        "1. РЕАЛЬНЫЙ DRR: если в контексте есть external_costs — посчитай реальный DRR = "
        "(ads_data.adv_sum + сумма external_costs) / ads_data.orders_sum_rub × 100. "
        "Сравни с DRR только по внутренней рекламе. Укажи разницу.\n"
        "2. КЛАСТЕРНЫЙ АНАЛИЗ: для каждой строки jam_clusters — оцени CTR "
        "(норма ≥0.5%, критично <0.3%), CPO = бюджет кластера / заказы кластера, "
        "рентабельность кластера. Выдели топ-3 лучших и худших по ROI.\n"
        "3. PER-SKU АНАЛИЗ: сопоставь ads_data и unit_economics по nmID/SKU — "
        "для каждого SKU: факт DRR vs max_drr из UNIT. Отметь превышения.\n"
        "4. ПЛАН VS ФАКТ: используй rnp_data — на сколько % рекламные расходы "
        "соответствуют плану? Где самые большие отклонения?\n"
        "5. КОНВЕРСИЯ: если есть mp_conv — сравни конверсию по типам размещения "
        "(поиск, каталог, рекомендации). Какой тип даёт лучший CPO?\n"
        "6. СВЯЗКА nmID: если есть nm_ref — используй для расшифровки nmID в "
        "jam_clusters и ads_data (подставляй название товара рядом с nmID).\n\n"
        "Доступные источники данных:\n"
        "  - ads_data: строки чеклиста с ненулевым adv_sum (последние 50 дней×SKU)\n"
        "  - unit_economics: UNIT-экономика с max_drr, маржой, себестоимостью по SKU\n"
        "  - rnp_data: РНП — план vs факт по заказам, выкупам, DRR, прибыли\n"
        "  - jam_clusters: рекламные кластеры с CTR, CPC, CPM, потенциалом прибыли\n"
        "  - external_costs: внешние расходы (блогеры, посевы) — включать в DRR!\n"
        "  - nm_ref: справочник nmID → название товара, отслеживаемые запросы\n"
        "  - mp_conv: конверсия по типу рекламного размещения\n\n"
        "Строго придерживайся формата ответа из системного промпта.\n\n"
        f"ДАННЫЕ:\n{_ctx_json(context)}"
    )
```

**Критерии корректности:**
- Блок заменяется целиком (от `elif query_type == "ads":` до конца строки с `return`)
- Все остальные `elif` блоки в функции `build_prompt` остаются без изменений
- `_ctx_json(context)` в конце сохраняется
- Строка не превышает разумной длины (многострочный return через скобки — паттерн уже есть в файле)

---

### Изменение 3: Добавить рекламный раздел в системный промпт

**Файл:** `config/system_prompt.md`

**Приоритет:** P0

#### Что добавить

**Вставить новый раздел ПОСЛЕ блока `# Правила полноты (КРИТИЧНО)` и ПЕРЕД блоком `# Стиль`:**

```markdown
# Анализ рекламы (специальные правила)

## Расчёт реального DRR
Стандартный DRR в чеклисте учитывает только внутреннюю рекламу WB.
Если в контексте есть `external_costs` — ВСЕГДА рассчитывай реальный DRR:
```
Реальный DRR = (adv_sum + Σ external_costs) / orders_sum_rub × 100
```
Показывай оба значения: DRR внутренний и DRR реальный. Разница — это "скрытая нагрузка".

## Анализ кластеров Джем (jam_clusters)
Для каждого кластера рассчитывай и указывай:
- **CTR**: норма ≥ 0.5%, предупреждение < 0.5%, критично < 0.3%
- **CPO кластера**: бюджет_кластера / заказы_кластера (в рублях)
- **ROI кластера**: (прибыль_кластера - бюджет_кластера) / бюджет_кластера × 100
- **Ёмкость**: сравни текущий охват с потенциалом кластера — недобираем или перегреваем?

Всегда выдавай: топ-3 кластера по ROI и топ-3 аутсайдера с рекомендацией действия.

## Сравнение DRR с max_drr по SKU
`unit_economics` содержит поле `max_drr` — максимально допустимый DRR для безубыточности.
При анализе рекламы ВСЕГДА сопоставляй фактический DRR из `ads_data` с `max_drr` из `unit_economics` по каждому nmID/SKU:
- DRR < max_drr × 0.8 — есть запас, можно масштабировать
- DRR в диапазоне max_drr × 0.8–1.0 — жёлтая зона, мониторить
- DRR > max_drr — красная зона, реклама убыточна по данному SKU

## Бенчмарки (использовать для оценки, не как абсолют)
| Метрика | Норма | Предупреждение | Критично |
|---------|-------|----------------|----------|
| CTR поиск | ≥ 0.5% | 0.3–0.5% | < 0.3% |
| DRR общий | < 15% | 15–25% | > 25% |
| DRR реальный (с внешними) | < 20% | 20–30% | > 30% |
| CPO | < max_drr × orders_avg | — | > unit margin |

## Внешние расходы
`external_costs` — это блогеры, посевы, внешний трафик. Они не отражаются в WB-аналитике,
но напрямую влияют на юнит-экономику. Если данные есть — всегда включай в итоговый DRR
и отдельной строкой показывай их долю в общем рекламном бюджете.
```

**Критерии корректности:**
- Новый раздел добавляется как отдельный H1 (`#`) — не вложенный
- Вставляется между `# Правила полноты (КРИТИЧНО)` и `# Стиль`
- Существующие разделы не изменяются и не удаляются
- Таблица в markdown-формате корректна (разделители `|`)

---

## ФАЗА 2 — NEXT

Реализуется **после** деплоя Фазы 1 и просмотра Railway-логов, подтверждающих загрузку `jam_clusters` с реальными именами колонок.

---

### Изменение 4a: Вычисляемые рекламные метрики в контексте

**Файл:** `src/processing/context.py`

**Приоритет:** P1

**Контекст:** `PeriodKPI` уже содержит поля `adv_sum`, `external_costs`, `orders_sum_rub`, `orders_count` — все вычисления возможны без обращения к шитам.

#### Что добавить

В блоке `elif query_type == "ads":`, **после загрузки всех шитов**, добавить вычисляемый блок:

```python
    # Вычисляемые рекламные метрики из PeriodKPI
    _adv = current_kpi.adv_sum
    _ext = current_kpi.external_costs or 0.0
    _orders_sum = current_kpi.orders_sum_rub
    _orders_count = current_kpi.orders_count

    if _adv is not None and _orders_sum:
        ctx["real_drr_percent"] = round((_adv + _ext) / _orders_sum * 100, 2)
    if _adv is not None and _orders_count:
        ctx["cpo_rub"] = round((_adv + _ext) / _orders_count, 2)
```

**Критерии корректности:**
- `current_kpi` уже вычислен в методе `build()` до блоков условий — переменная доступна
- Деление только если знаменатель не `None` и не `0`
- Никакого `try/except` — используется уже существующий паттерн `if x is not None`
- Ключи `real_drr_percent` и `cpo_rub` добавляются в `ctx` только если вычисление возможно

---

### Изменение 4b: Кластерный препроцессинг

**Файл:** `src/processing/context.py`

**Статус:** ЗАМОРОЖЕНО до подтверждения схемы колонок

**Условие разморозки:** в Railway-логах после Фазы 1 появятся строки вида:
```
Built context for 'ads': ~XXXXX tokens, Y anomalies
```
и в `jam_clusters` будут видны реальные ключи словарей. Зафиксировать имена колонок (например: `cluster_name`, `ctr`, `cpc`, `budget`, `orders`, `profit_potential`).

**После подтверждения:** добавить в `ads` branch предвычисленные поля:
```python
    # После загрузки jam_clusters — только если колонки подтверждены
    if ctx.get("jam_clusters"):
        # top/bottom clusters by ROI — вычислять здесь, не в Gemini
        ...
```

---

### Изменение 5: CTR-правила в anomaly detection

**Файл:** `config/rules.yaml`

**Приоритет:** P1
**Сложность:** только YAML, изменений кода нет

**Добавить в конец файла** (после блока `buyout_percent_month`):

```yaml
  # ── CTR поиска ──────────────────────────────────────────────────────────
  - metric: ctr_search
    condition: lt
    threshold: 0.5
    severity: warning
    message_template: "CTR поиска {sku}: {value:.2f}% (предупреждение < {threshold:.1f}%)"
    action: "Проверить релевантность ставок и визуал карточки"

  - metric: ctr_search
    condition: lt
    threshold: 0.3
    severity: critical
    message_template: "CTR поиска {sku}: {value:.2f}% (критично < {threshold:.1f}%)"
    action: "Остановить рекламу по данному кластеру и пересмотреть карточку"
```

**Критерии корректности:**
- `ctr_search` — существующее поле `PeriodKPI` (строка 34 `kpi.py`), уже вычисляется `KPICalculator.calculate()`
- Структура соответствует `AnomalyRule` Pydantic-модели: `metric`, `condition`, `threshold`, `severity`, `message_template`, `action`
- `condition: lt` корректен (CTR ниже порога — плохо)
- `{value:.2f}` — два знака после запятой для CTR
- Два правила добавляются как отдельные элементы списка `rules:`

---

### Изменение 6: Per-SKU DRR vs max_drr

**Файл:** `src/processing/anomaly.py`

**Приоритет:** P1
**Сложность:** новый метод, изменение кода

**Добавить новый метод в класс `AnomalyChecker`** после `check_all()`:

```python
def check_sku_vs_unit(
    self,
    ads_rows: List[dict],
    unit_rows: List[dict],
) -> List[Anomaly]:
    """
    Compare actual DRR per SKU against max_drr from unit economics.
    Returns Anomaly for each SKU where actual DRR > max_drr.
    """
    # Build max_drr lookup: nmID/sku → max_drr value
    max_drr_map: dict[str, float] = {}
    for row in unit_rows:
        nm_id = str(row.get("nm_id", row.get("nmID", row.get("sku", ""))))
        if not nm_id:
            continue
        raw = row.get("max_drr")
        if raw in (None, "", "-"):
            continue
        try:
            max_drr_map[nm_id] = float(str(raw).replace(" ", "").replace(",", "."))
        except (ValueError, TypeError):
            pass

    if not max_drr_map:
        return []

    # Group ads_rows by SKU, sum adv_sum and orders_sum per SKU
    sku_adv: dict[str, float] = {}
    sku_orders: dict[str, float] = {}
    for row in ads_rows:
        nm_id = str(row.get("nm_id", row.get("nmID", row.get("sku", ""))))
        if not nm_id:
            continue
        adv = row.get("adv_sum")
        orders = row.get("orders_sum_rub")
        for target, field_val in [(sku_adv, adv), (sku_orders, orders)]:
            if field_val in (None, "", "-"):
                continue
            try:
                v = float(str(field_val).replace(" ", "").replace(",", "."))
                target[nm_id] = target.get(nm_id, 0.0) + v
            except (ValueError, TypeError):
                pass

    anomalies: List[Anomaly] = []
    for nm_id, max_drr in max_drr_map.items():
        adv_total = sku_adv.get(nm_id)
        orders_total = sku_orders.get(nm_id)
        if adv_total is None or orders_total is None or orders_total == 0:
            continue
        actual_drr = adv_total / orders_total * 100
        if actual_drr > max_drr:
            anomalies.append(Anomaly(
                metric="drr_vs_max_drr",
                severity="critical" if actual_drr > max_drr * 1.3 else "warning",
                message=f"DRR {nm_id}: {actual_drr:.1f}% превышает max_drr {max_drr:.1f}%",
                action="Снизить ставки или пересмотреть ценообразование",
                sku=nm_id,
                value=round(actual_drr, 1),
                threshold=max_drr,
                alert_key=_make_alert_key("drr_vs_max_drr", nm_id),
            ))

    return sorted(anomalies, key=lambda a: 0 if a.severity == "critical" else 1)
```

**Вызов метода** — добавить в `check_all()` в `anomaly.py`:

```python
def check_all(self, kpi: PeriodKPI, checklist_rows: List[dict]) -> List[Anomaly]:
    # СУЩЕСТВУЮЩИЙ КОД — не менять
    seen: set[str] = set()
    result: List[Anomaly] = []
    for a in self.check_kpi(kpi) + self.check_per_sku(checklist_rows):
        if a.alert_key not in seen:
            seen.add(a.alert_key)
            result.append(a)
    return result
```

**Внимание:** `check_sku_vs_unit()` — новый метод с отдельной сигнатурой. Его вызов из `check_all()` требует `unit_rows`. Два варианта интеграции:

**Вариант A (рекомендуемый):** вызывать `check_sku_vs_unit()` явно в `context.py` при построении контекста для `/ads` — добавить результаты в `ctx["ads_anomalies"]`

**Вариант B:** изменить сигнатуру `check_all()` с добавлением опционального параметра `unit_rows=None` — сложнее, меняет публичный API

**Реализующий субагент должен выбрать Вариант A** и добавить в `context.py` ads-branch:
```python
    # Добавить после загрузки шитов (требует unit_rows)
    ads_anomalies = checker.check_sku_vs_unit(
        ctx.get("ads_data", []),
        ctx.get("unit_economics", [])
    )
    if ads_anomalies:
        ctx["ads_anomalies"] = [
            {"severity": a.severity, "sku": a.sku, "message": a.message, "action": a.action}
            for a in ads_anomalies
        ]
```

**Проблема:** `ContextBuilder` не получает `AnomalyChecker` как зависимость — только `checker` в `main.py`. Нужно либо передать `checker` в `ContextBuilder.__init__()`, либо вызывать `check_sku_vs_unit()` в хэндлере `cmd_ads`. **Реализующий субагент должен проверить `main.py` и `handlers.py` и выбрать наименее инвазивный способ.**

---

## ФАЗА 3 — LATER

Не реализовывать в текущем спринте. Заморожено.

| # | Задача | Условие разморозки |
|---|--------|--------------------|
| 7 | Cluster trend analysis: хранить jam-снэпшоты в кэше для временного сравнения | После подтверждения стабильной структуры jam-кластеров |
| 8 | Bid optimization: unit.max_drr + jam.cpc → конкретные рекомендации по ставкам | После реализации 4b |
| 9 | Automated ad push alerts (отдельный job, не anomaly checker) | После стабилизации Фаз 1 и 2 |
| 10 | Delta anomaly detection (CTR drop >30%/day) — требует рефактора AnomalyChecker с временными сравнениями | Отдельная задача, не связана с текущим спринтом |

---

## Метрики успеха

**Ведущие (наблюдать сразу после деплоя Фазы 1):**
- Railway-логи: `Built context for 'ads': ~XXXXX tokens` — значение должно вырасти с ~2-5K до ~10-20K токенов
- В логах появляются ключи `jam_clusters`, `external_costs` в контексте ads
- `/ads` в боте возвращает кластерный анализ с CTR/CPO цифрами (не просто список SKU с DRR)

**Запаздывающие (наблюдать через 1-2 недели использования):**
- Ответы на рекламные вопросы содержат раздел с реальным DRR (adv + external)
- В `/alerts` появляются CTR-аномалии когда CTR падает ниже 0.5%

---

## Открытые вопросы

| Вопрос | Кто отвечает | Блокирует |
|--------|-------------|-----------|
| Какие точные имена колонок в листе "Джем"? (нужно для 4b и 8) | Данные из логов после Фазы 1 | 4b, 8 |
| Есть ли поле `max_drr` в листе "UNIT" или это вычисляемое поле? | Проверить в логах `unit_economics` из контекста | 6 |
| `AnomalyChecker` не получает `unit_rows` в текущем API — где правильнее всего интегрировать `check_sku_vs_unit`? | Реализующий субагент, после чтения `main.py` | 6 |
| `mp_conv` — какова структура строк? (нужно для промпта) | Данные из логов после Фазы 1 | 4b |

---

## Ограничения реализации (строго соблюдать)

1. **Не создавать новые файлы в Фазе 1** — только редактировать существующие
2. **Не добавлять новые команды** (`/ads_clusters`, `/ads_budget`) — не входит в скоуп
3. **Не изменять поведение других query_type** (`daily`, `weekly`, `plan`, `stocks`, `ask`) — их блоки в `context.py` не трогать
4. **Graceful fallback обязателен** — все новые P1/P2 ключи загружать через `if all_sheets.get("key"):`, никогда не `all_sheets["key"]`
5. **Только русский язык** — в промптах, системном промпте, сообщениях об ошибках
6. **Не добавлять `try/except`** сверх того, что уже есть — паттерн проекта: безопасный доступ через `.get()` и проверку на None
7. **Сохранять отступы и стиль** — файлы используют 4 пробела, двойные кавычки в строках промптов

---

## Чеклист приёмки Фазы 1

- [ ] `context.py`: блок `ads` содержит 7 ключей (`ads_data`, `unit_economics`, `rnp_data`, `jam_clusters`, `external_costs`, `nm_ref`, `mp_conv`)
- [ ] `context.py`: `trim_candidates` содержит `mp_conv`, `nm_ref`, `rnp_data`; `jam_clusters` стоит после `fin_report_sku` и других P1-ключей
- [ ] `context.py`: остальные query_type блоки (`daily`, `weekly`, `plan`, `stocks`, `ask`) не изменены
- [ ] `prompts.py`: блок `ads` содержит 6 пронумерованных инструкций с перечислением источников
- [ ] `prompts.py`: остальные блоки (`daily`, `weekly`, `plan`, `stocks`, `ask`) не изменены
- [ ] `system_prompt.md`: содержит раздел `# Анализ рекламы (специальные правила)` с формулой реального DRR и таблицей бенчмарков
- [ ] `system_prompt.md`: существующие разделы не изменены и не удалены
- [ ] Railway деплой проходит без ошибок (нет `ImportError`, `KeyError`, `AttributeError`)
- [ ] `/ads` в боте возвращает ответ без `❌` сообщения об ошибке
