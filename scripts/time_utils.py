#!/usr/bin/env python3
"""
time_utils.py
────────────────
Shared timezone helpers for HealthFit scheduling and reporting flows.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIMEZONE_ENV_VAR = "HEALTHFIT_TIMEZONE"
DEFAULT_TIMEZONE = "Asia/Taipei"


def get_healthfit_timezone_name() -> str:
    """Return the configured IANA timezone name."""
    return os.environ.get(TIMEZONE_ENV_VAR, DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE


def get_healthfit_timezone() -> ZoneInfo:
    """Resolve the configured timezone or raise a clear runtime error."""
    name = get_healthfit_timezone_name()
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(
            f"Invalid {TIMEZONE_ENV_VAR} value: {name!r}. Use an IANA timezone such as 'Asia/Taipei'."
        ) from exc


def now_local() -> datetime:
    """Return timezone-aware current datetime in the configured timezone."""
    return datetime.now(get_healthfit_timezone())


def today_local() -> date:
    """Return current local date in the configured timezone."""
    return now_local().date()


def local_date_from_iso(timestamp: str | None) -> date:
    """Return the configured-local calendar date for an ISO-8601 timestamp."""
    if not timestamp:
        return today_local()
    normalized = timestamp.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    tz = get_healthfit_timezone()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz).date()


def local_date_str_from_iso(timestamp: str | None) -> str:
    """Return the configured-local YYYY-MM-DD for an ISO-8601 timestamp."""
    return local_date_from_iso(timestamp).isoformat()


def group_rows_by_local_date(
    rows: Iterable[Mapping[str, Any]],
    *,
    timestamp_key: str = "log_datetime",
) -> dict[str, list[dict[str, Any]]]:
    """Group row-like mappings by configured-local calendar date."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row_dict = dict(row)
        local_day = local_date_str_from_iso(str(row_dict.get(timestamp_key) or ""))
        grouped.setdefault(local_day, []).append(row_dict)
    return grouped
