# WB AI-Agent MVP

Telegram-бот с AI-аналитикой для управления кабинетом Wildberries.

**Стек**: Python 3.11 · Gemini 2.0 Flash · Google Sheets API · python-telegram-bot v21 · SQLite · Railway

## Быстрый старт (деплой на Railway)

### Шаг 1 — Google Cloud (GCP)

1. Открой [console.cloud.google.com](https://console.cloud.google.com) → создай проект
2. **APIs & Services** → Enable **Google Sheets API v4**
3. **IAM & Admin** → **Service Accounts** → Create → Name: `wb-agent-reader`
4. Создай JSON-ключ: Service Account → **Keys** → **Add Key** → JSON
5. Закодируй в base64:
   ```bash
   base64 -w 0 your-key.json  # Linux/Mac
   ```
6. Сохрани результат как `GOOGLE_CREDENTIALS_JSON`

### Шаг 2 — Google Sheets

1. Открой [таблицу](https://docs.google.com/spreadsheets/d/1DjfLItDaSZRJNMKId5mC_fJMpvDSPkcWeHD_Sy7RmTE)
2. **Share** → добавить email Service Account как **Viewer**

### Шаг 3 — Gemini API

1. Открой [aistudio.google.com](https://aistudio.google.com)
2. **Get API Key** → Create Key → привязать к GCP проекту
3. Сохрани как `GEMINI_API_KEY`

### Шаг 4 — Telegram Bot

1. Напиши [@BotFather](https://t.me/botfather) → `/newbot` → получи токен
2. Получи свой Telegram ID через [@userinfobot](https://t.me/userinfobot)

### Шаг 5 — Railway

1. [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. **Settings** → **Add Volume** → mount path: `/app/data`
3. Установи все env vars (см. ниже)
4. Push код в GitHub — Railway задеплоит автоматически

---

## Env Variables

Все переменные указываются в Railway Dashboard (Settings → Variables) или в `.env` для локальной разработки.

| Variable | Required | Example | Description |
|---|---|---|---|
| `SPREADSHEET_ID` | ✅ | `1DjfLIt...` | ID Google Sheets таблицы |
| `GOOGLE_CREDENTIALS_JSON` | ✅ | `eyJ0...` | Base64-encoded service account JSON |
| `GEMINI_API_KEY` | ✅ | `AIzaSy...` | Google AI Studio API key |
| `GEMINI_MODEL` | — | `gemini-2.0-flash` | Gemini model name |
| `TELEGRAM_BOT_TOKEN` | ✅ | `123456:ABC...` | Token from @BotFather |
| `TELEGRAM_ALLOWED_IDS` | ✅ | `233085299` | Comma-separated Telegram user IDs |
| `OWNER_CHAT_ID` | ✅ | `233085299` | Chat ID for system alerts |
| `DAILY_REPORT_HOUR_UTC` | — | `6` | Daily report hour in UTC (6 = 09:00 MSK) |
| `WEEKLY_REPORT_HOUR_UTC` | — | `6` | Weekly report hour in UTC |
| `WEEKLY_REPORT_WEEKDAY` | — | `0` | Weekday for weekly report (0=Mon) |
| `CACHE_TTL_MINUTES` | — | `5` | Cache refresh interval in minutes |
| `DATA_DIR` | — | `/app/data` | Path for SQLite DB (must be on Volume) |
| `LOG_LEVEL` | — | `INFO` | Logging level: DEBUG/INFO/WARNING/ERROR |

---

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие и статус системы |
| `/report` | Дневной отчёт по кабинету |
| `/week` | Недельный анализ (WoW динамика) |
| `/plan` | Выполнение плана месяца |
| `/stocks` | Риски по остаткам товаров |
| `/ads` | Эффективность рекламы (DRR, CTR) |
| `/alerts` | Активные аномалии прямо сейчас |
| `/ask [вопрос]` | Любой вопрос к AI-аналитику |
| `/refresh` | Принудительное обновление кэша |
| `/status` | Статус системы (uptime, кэш, аномалии) |

**Свободный текст** без `/` также обрабатывается как вопрос к AI.

---

## Автоматические уведомления

| Уведомление | Время | Условие |
|---|---|---|
| Дневной отчёт | Пн–Пт 09:00 МСК | Каждый рабочий день |
| Недельный анализ | Пн 09:30 МСК | Каждый понедельник |
| Алерт об остатках | До 10 мин с момента | Остаток < 7 дней |
| Алерт о рекламе | До 10 мин с момента | DRR > 30% |
| Алерт о плане | До 10 мин с момента | Выполнение < 65% |
| Алерт ошибки системы | Немедленно | Сбой scheduled job |

---

## Локальная разработка

```bash
# Клонировать репозиторий
git clone <repo-url>
cd wb_agent_mvp

# Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Установить зависимости
pip install -r requirements.txt

# Скопировать и заполнить .env
cp .env.example .env
# Отредактировать .env с реальными значениями

# Создать папку для данных
mkdir -p data

# Запустить тесты
pytest tests/ -v

# Запустить бота локально
DATA_DIR=./data python main.py
```

---

## Архитектура

```
main.py
├── aiohttp health server (:$PORT/health)
├── PTB Application (polling)
│   ├── Command Handlers (10 команд)
│   ├── Error Handler
│   └── JobQueue (встроенный APScheduler)
│       ├── cache_refresh (каждые 5 мин)
│       ├── alert_check (каждые 10 мин)
│       ├── daily_summary (пн-пт 09:00 UTC)
│       └── weekly_analysis (пн 09:30 UTC)
│
src/
├── settings.py          # Pydantic Settings (fail-fast validation)
├── logging_config.py    # Structured logging setup
├── sheets/
│   ├── reader.py        # SheetsReader (sync, single ThreadPoolExecutor, tenacity retry)
│   └── mapping.py       # Tab name mapping
├── storage/
│   └── cache.py         # aiosqlite (WAL mode, transactional writes, alert dedup)
├── processing/
│   ├── kpi.py           # KPICalculator + PeriodKPI dataclass
│   ├── anomaly.py       # AnomalyChecker + Pydantic rules.yaml validation
│   └── context.py       # ContextBuilder (query-aware JSON assembly)
├── gemini/
│   ├── client.py        # google-genai SDK + AsyncRetrying
│   └── prompts.py       # Prompt templates per query type
└── bot/
    ├── handlers.py      # All Telegram handlers + access control
    └── formatter.py     # Message splitting + MarkdownV2 escaping

config/
├── rules.yaml           # Anomaly thresholds (validated by Pydantic at startup)
└── system_prompt.md     # Gemini system instruction
```

### Ключевые архитектурные решения

| Решение | Причина |
|---|---|
| `google-genai` (не `google-generativeai`) | Старый SDK deprecated с ноября 2025 |
| PTB JobQueue (не отдельный APScheduler) | Избежать конфликт двух планировщиков в одном event loop |
| `ThreadPoolExecutor(max_workers=1)` для gspread | gspread синхронный, credentials не thread-safe |
| SQLite WAL mode + busy_timeout=5000 | Без WAL — `database is locked` при конкурентном доступе |
| Railway Volume на `/app/data` | Контейнер ephemeral — без Volume SQLite теряется при рестарте |
| Транзакционная запись кэша (`BEGIN IMMEDIATE`) | Частичный refresh → смешанные данные |
| Pydantic Settings + AnomalyRule | Fail-fast при старте, не в рантайме |

---

## Стоимость

| Компонент | Цена |
|---|---|
| Gemini 2.0 Flash | ~$0.09/мес при стандартной нагрузке |
| Railway Hobby | $5–20/мес |
| **Итого** | **$6–21/мес** |

---

## Листы Google Sheets

Лист плана имеет постоянное техническое имя `plan_actual` — обновлять вручную каждый месяц **не нужно**.
Если в таблице появится новый формат листа — обновить имя в `src/sheets/mapping.py` → `P0_SHEETS["plan_actual"]`.
