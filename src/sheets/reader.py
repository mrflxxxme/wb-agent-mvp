"""
Google Sheets reader.

Design decisions:
- Fully synchronous (gspread is sync-only; credential object is NOT thread-safe)
- Single dedicated ThreadPoolExecutor (max_workers=1) to avoid concurrent gspread calls
- tenacity retry on APIError: exponential backoff 2s → 60s, up to 5 attempts
- All async callers must use: await loop.run_in_executor(_sheets_executor, reader.read_all_p0)
"""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Dict, List, Optional

import gspread
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.sheets.mapping import P0_SHEETS, P1_SHEETS

logger = logging.getLogger(__name__)

# Single-thread executor — gspread credentials are not thread-safe
_sheets_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="gspread"
)


class SheetsReader:
    """Read-only Google Sheets client backed by a Service Account."""

    def __init__(self, credentials: dict, spreadsheet_id: str) -> None:
        self._gc = gspread.service_account_from_dict(credentials)
        self._spreadsheet_id = spreadsheet_id
        self._ss: Optional[gspread.Spreadsheet] = None

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        if self._ss is None:
            self._ss = self._gc.open_by_key(self._spreadsheet_id)
        return self._ss

    @retry(
        retry=retry_if_exception_type(gspread.exceptions.APIError),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _read_sheet_sync(self, tab_name: str) -> List[dict]:
        """Read a worksheet and return rows as list of dicts (row 1 = headers)."""
        ss = self._get_spreadsheet()
        try:
            ws = ss.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            logger.warning("Sheet tab '%s' not found — skipping", tab_name)
            return []
        records = ws.get_all_records(expected_headers=[])
        logger.debug("Read %d rows from '%s'", len(records), tab_name)
        return records

    def probe(self) -> str:
        """Quick connectivity check — returns spreadsheet title or raises."""
        ss = self._get_spreadsheet()
        return ss.title

    def read_all_p0(self) -> Dict[str, List[dict]]:
        """
        Read all P0 sheets synchronously.
        Call via: await loop.run_in_executor(_sheets_executor, reader.read_all_p0)
        Returns dict keyed by internal Python names (not tab names).
        """
        result: Dict[str, List[dict]] = {}
        for key, tab_name in P0_SHEETS.items():
            try:
                result[key] = self._read_sheet_sync(tab_name)
            except gspread.exceptions.APIError as e:
                logger.error("Failed to read P0 sheet '%s' (%s): %s", key, tab_name, e)
                raise  # Let the caller (cache_refresh_job) handle this
        return result

    def read_p1(self) -> Dict[str, List[dict]]:
        """Read P1 sheets (best-effort, missing sheets return empty list)."""
        result: Dict[str, List[dict]] = {}
        for key, tab_name in P1_SHEETS.items():
            try:
                result[key] = self._read_sheet_sync(tab_name)
            except Exception as e:
                logger.warning("P1 sheet '%s' unavailable: %s", tab_name, e)
                result[key] = []
        return result

    def read_all(self) -> Dict[str, List[dict]]:
        """Read P0 + P1 sheets."""
        data = self.read_all_p0()
        data.update(self.read_p1())
        return data
