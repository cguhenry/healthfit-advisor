#!/usr/bin/env python3
"""
time_utils.py
────────────────
Shared timezone helpers for HealthFit scheduling and reporting flows.
"""

from __future__ import annotations

import os
from datetime import date, datetime
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
