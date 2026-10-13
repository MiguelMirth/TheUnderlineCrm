"""
Live credit balances for the estimate.

Apollo and Tavily report what is left, and when it starts over.
Cursor has no balance API. Its allowance is the env ceiling, and the cycle
turns on the 13th. Gemini is free while Google accepts the request.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

APOLLO_CREDITS_URL = "https://api.apollo.io/api/v1/usage_stats/credit_usage_stats"
TAVILY_USAGE_URL = "https://api.tavily.com/usage"
BALANCE_TTL = timedelta(minutes=15)


def cursor_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The current Cursor cycle: the 13th of this month, or last month if that day has not arrived."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def on_13(year: int, month: int) -> datetime:
        return datetime(year, month, 13, tzinfo=timezone.utc)

    if moment.day >= 13:
        start = on_13(moment.year, moment.month)
        if moment.month == 12:
            end = on_13(moment.year + 1, 1)
        else:
            end = on_13(moment.year, moment.month + 1)
    else:
        if moment.month == 1:
            start = on_13(moment.year - 1, 12)
        else:
            start = on_13(moment.year, moment.month - 1)
        end = on_13(moment.year, moment.month)
    return start, end


def tavily_refresh(now: datetime | None = None) -> str:
    """Tavily plan credits start over on the first of each month."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if moment.month == 12:
        nxt = datetime(moment.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(moment.year, moment.month + 1, 1, tzinfo=timezone.utc)
    return nxt.date().isoformat()


def _date_only(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else ""


def _cached(store: Any, provider: str) -> dict[str, Any] | None:
    row = store.cache_get("engine", "balance", provider)
    if not row or not isinstance(row.get("payload"), dict):
        return None
    fetched = datetime.fromisoformat(str(row["fetched_at"]))
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched > BALANCE_TTL:
        return None
    return row["payload"]


def _store_balance(store: Any, provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    store.cache_put("engine", "balance", provider, payload, 0)
    return payload


def fetch_apollo_balance() -> dict[str, Any] | None:
    key = os.getenv("APOLLO_API_KEY", "").strip()
    if not key:
        return None
    try:
        response = requests.post(
            APOLLO_CREDITS_URL,
            headers={"Content-Type": "application/json", "x-api-key": key},
            timeout=8,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError):
        return None
    stats = (body.get("credit_usage_stats") or {}).get("lead_credit") or {}
    left = stats.get("left_over")
    if left is None:
        return None
    return {"remaining": float(left), "refreshes_on": _date_only((body.get("current_credit_cycle") or {}).get("end_date"))}


def fetch_tavily_balance() -> dict[str, Any] | None:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        return None
    try:
        response = requests.get(
            TAVILY_USAGE_URL,
            headers={"Authorization": f"Bearer {key}"},
            timeout=8,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError):
        return None
    account = body.get("account") or {}
    limit = account.get("plan_limit")
    used = account.get("plan_usage")
    if limit is None:
        key_info = body.get("key") or {}
        limit = key_info.get("limit")
        used = key_info.get("usage")
    if limit is None:
        return None
    remaining = max(0.0, float(limit) - float(used or 0))
    return {"remaining": remaining, "refreshes_on": tavily_refresh()}


def live_balance(store: Any, provider: str) -> dict[str, Any] | None:
    """Apollo or Tavily remaining credits. Cached for 15 minutes. None when the call cannot be made."""
    cached = _cached(store, provider)
    if cached is not None:
        return cached
    fetched = fetch_apollo_balance() if provider == "apollo" else fetch_tavily_balance() if provider == "tavily" else None
    if fetched is None:
        return None
    return _store_balance(store, provider, fetched)
