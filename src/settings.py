"""
Centralized configuration using pydantic-settings.
All env vars are validated at import time — fail fast if required vars are missing.
"""
from __future__ import annotations

import base64
import json
import os
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Telegram ───────────────────────────────────────────
    telegram_bot_token: str
    # Comma-separated numeric user IDs, e.g. "233085299,987654321"
    telegram_allowed_ids: str
    owner_chat_id: int

    # ── Google Sheets ──────────────────────────────────────
    spreadsheet_id: str
    # Base64-encoded service account JSON
    google_credentials_json: str

    # ── Gemini AI ──────────────────────────────────────────
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"

    # ── Storage ────────────────────────────────────────────
    data_dir: str = "/app/data"
    cache_ttl_minutes: int = 5

    # ── Logging ────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Schedule (UTC) ─────────────────────────────────────
    daily_report_hour_utc: int = 6
    weekly_report_hour_utc: int = 6
    weekly_report_weekday: int = 0  # 0 = Monday

    # ── Derived properties ─────────────────────────────────

    @property
    def allowed_ids(self) -> List[int]:
        """Parse comma-separated IDs into a list of integers."""
        return [int(x.strip()) for x in self.telegram_allowed_ids.split(",") if x.strip()]

    @property
    def google_credentials(self) -> dict:
        """Decode base64 service account JSON into a dict."""
        try:
            raw = base64.b64decode(self.google_credentials_json).decode("utf-8")
            return json.loads(raw)
        except Exception as exc:
            raise ValueError(
                "GOOGLE_CREDENTIALS_JSON is not valid base64-encoded JSON"
            ) from exc

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "cache.db")

    model_config = {"env_file": ".env", "extra": "ignore"}


# Module-level singleton — raises ValidationError at import time if required vars missing
settings = Settings()
