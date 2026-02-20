"""Shared serialization helpers for API responses."""

from __future__ import annotations

from datetime import datetime, timezone


def _fmt_dt(val: datetime | str | None) -> str:
    """Format a datetime as an ISO 8601 UTC string that JavaScript can parse correctly."""
    if val is None:
        return ""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.isoformat()
    s = str(val).strip()
    if not s:
        return ""
    if "T" not in s:
        s = s.replace(" ", "T")
    if not s.endswith("Z") and "+" not in s and "-" not in s[10:]:
        s += "Z"
    return s
