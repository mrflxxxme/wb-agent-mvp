"""
Telegram message formatting utilities.

Telegram limits:
- Max message length: 4096 chars (we use 2000 for safety)
- MarkdownV2 requires escaping many special characters
"""
from __future__ import annotations

import re
from typing import List

MAX_MESSAGE_LENGTH = 2500


# Characters that must be escaped in MarkdownV2
_MD2_ESCAPE = re.compile(r"([_\*\[\]\(\)~`>#+\-=|{}.!\\])")


def escape_md2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _MD2_ESCAPE.sub(r"\\\1", text)


def split_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """
    Split a long message into parts <= max_len chars.
    Tries to split at newlines to preserve formatting.
    """
    if len(text) <= max_len:
        return [text]

    parts: List[str] = []
    current = ""
    for line in text.split("\n"):
        # +1 for the newline character
        if len(current) + len(line) + 1 > max_len:
            if current:
                parts.append(current.rstrip())
                current = ""
            # Handle a single line longer than max_len
            while len(line) > max_len:
                parts.append(line[:max_len])
                line = line[max_len:]
        current += line + "\n"
    if current.strip():
        parts.append(current.rstrip())
    return parts


def format_anomaly_list(anomalies) -> str:
    """Format a list of Anomaly objects into a Telegram-ready string."""
    if not anomalies:
        return "✅ Активных аномалий нет. Все показатели в норме."

    lines = ["*Активные аномалии:*\n"]
    criticals = [a for a in anomalies if a.severity == "critical"]
    warnings = [a for a in anomalies if a.severity == "warning"]

    if criticals:
        lines.append("🚨 *КРИТИЧНО:*")
        for a in criticals:
            lines.append(f"  • {a.message}")
            lines.append(f"    💡 {a.action}")
        lines.append("")

    if warnings:
        lines.append("⚠️ *ВНИМАНИЕ:*")
        for a in warnings:
            lines.append(f"  • {a.message}")
            lines.append(f"    💡 {a.action}")

    return "\n".join(lines)


def format_status(
    last_updated_str: str,
    anomaly_counts: dict,
    sheets_ok: bool,
    uptime_seconds: int,
    version: str = "1.0.0",
) -> str:
    """Format /status response."""
    uptime_h = uptime_seconds // 3600
    uptime_m = (uptime_seconds % 3600) // 60
    sheets_status = "✅" if sheets_ok else "❌"
    return (
        f"*WB AI-Agent v{version}*\n\n"
        f"🕐 Последнее обновление кэша: {last_updated_str}\n"
        f"📊 Аномалий: 🚨 {anomaly_counts.get('critical', 0)} критичных, "
        f"⚠️ {anomaly_counts.get('warning', 0)} предупреждений\n"
        f"📋 Google Sheets: {sheets_status}\n"
        f"⏱ Uptime: {uptime_h}ч {uptime_m}мин"
    )
