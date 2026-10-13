"""CRM snapshot: paged read (read-only), TTL, refresh rules, and the Start blockers that come from the CRM side."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine import crm
from engine.crm import CrmUnavailable, crm_blockers, crm_status, ensure_snapshot, fetch_crm_snapshot
from engine.presets import PRESETS

PRESET = PRESETS["underline"]
BOARD = "18401545002"


class FakeMonday:
    """Returns queued responses in order and records every call. Never touches the network."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def execute_query(self, query, variables=None):
        self.calls.append(variables or {})
        return self.responses.pop(0)


def _item(name, email="", first="", last="", website="", status="", group="group_mm0xbmrj"):
    cols = [
        {"id": "email_mm0xb00t", "text": email, "value": ""},
        {"id": "text_mm0xjngp", "text": first, "value": ""},
        {"id": "text_mm0xg7qz", "text": last, "value": ""},
        {"id": "text_mm0xt1wm", "text": website, "value": ""},
        {"id": "status", "text": status, "value": ""},
    ]
    return {"id": name, "name": name, "group": {"id": group}, "column_values": cols}


def _pages():
    first = {
        "data": {
            "boards": [
                {
                    "items_page": {
                        "cursor": "c2",
                        "items": [_item("Acme Foods", email="Jane@Acme.com", first="Jane", last="Doe", website="https://www.acme.com/")],
                    }
                }
            ]
        }
    }
    second = {
        "data": {
            "next_items_page": {
                "cursor": None,
                "items": [_item("Replied Co", email="x@replied.com", status="Replied", group="group_mm0xj5rd")],
            }
        }
    }
    return [first, second]


def test_fetch_pages_through_the_board_and_normalizes_rows():
    monday = FakeMonday(_pages())
    snap = fetch_crm_snapshot(monday, BOARD, PRESET.crm)
    assert [r["name"] for r in snap["rows"]] == ["Acme Foods", "Replied Co"]
    acme = snap["rows"][0]
    assert acme["email"] == "jane@acme.com"
    assert acme["first"] == "Jane" and acme["last"] == "Doe"
    assert acme["website"] == "https://www.acme.com/"
    assert len(monday.calls) == 2
    assert monday.calls[1]["cursor"] == "c2"


def test_a_failed_read_is_never_an_empty_board():
    with pytest.raises(CrmUnavailable, match="Monday read failed"):
        fetch_crm_snapshot(FakeMonday([None]), BOARD, PRESET.crm)


def test_a_missing_board_is_refused():
    with pytest.raises(CrmUnavailable, match="was not returned"):
        fetch_crm_snapshot(FakeMonday([{"data": {"boards": []}}]), BOARD, PRESET.crm)


def test_fresh_snapshot_is_used_without_calling_monday(store, monkeypatch):
    monkeypatch.setenv("CRM_SNAPSHOT_TTL_HOURS", "12")
    store.crm_snapshot_put(BOARD, {"rows": []})

    def boom():
        raise AssertionError("Monday must not be called for a fresh snapshot")

    meta = ensure_snapshot(store, PRESET, monday_factory=boom)
    assert meta["refreshed"] is False


def test_stale_snapshot_is_refreshed_once(store, monkeypatch):
    monkeypatch.setenv("CRM_SNAPSHOT_TTL_HOURS", "1")
    store.crm_snapshot_put(BOARD, {"rows": []})
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    monday = FakeMonday(_pages())
    meta = ensure_snapshot(store, PRESET, monday_factory=lambda: monday, now=future)
    assert meta["refreshed"] is True
    assert meta["stale_before"] is True
    assert store.crm_snapshot_get(BOARD)["payload"]["rows"][0]["name"] == "Acme Foods"


def test_force_refresh_ignores_ttl(store):
    store.crm_snapshot_put(BOARD, {"rows": []})
    monday = FakeMonday(_pages())
    meta = ensure_snapshot(store, PRESET, monday_factory=lambda: monday, force=True)
    assert meta["refreshed"] is True


def test_no_snapshot_and_no_key_is_refused(store, monkeypatch):
    monkeypatch.delenv("MONDAY_API_KEY", raising=False)
    with pytest.raises(CrmUnavailable, match="MONDAY_API_KEY is not set"):
        ensure_snapshot(store, PRESET)


def test_start_blocked_when_no_snapshot_and_no_key(store, monkeypatch):
    monkeypatch.delenv("MONDAY_API_KEY", raising=False)
    assert crm_blockers(store, PRESET) == ["MONDAY_API_KEY is not set, so the CRM blocklist cannot be read."]


def test_start_not_blocked_by_a_fresh_snapshot_even_without_key(store, monkeypatch):
    monkeypatch.delenv("MONDAY_API_KEY", raising=False)
    store.crm_snapshot_put(BOARD, {"rows": []})
    assert crm_blockers(store, PRESET) == []


def test_stale_snapshot_without_key_blocks_start(store, monkeypatch):
    monkeypatch.delenv("MONDAY_API_KEY", raising=False)
    store.crm_snapshot_put(BOARD, {"rows": []})
    later = datetime.now(timezone.utc) + timedelta(hours=100)
    assert crm_blockers(store, PRESET, now=later) == [
        "The CRM snapshot is stale and MONDAY_API_KEY is not set, so it cannot be refreshed."
    ]


def test_ttl_reads_env_and_falls_back_on_garbage(monkeypatch):
    monkeypatch.setenv("CRM_SNAPSHOT_TTL_HOURS", "6")
    assert crm.snapshot_ttl_hours() == 6.0
    monkeypatch.setenv("CRM_SNAPSHOT_TTL_HOURS", "soon")
    assert crm.snapshot_ttl_hours() == crm.DEFAULT_TTL_HOURS


def test_status_reports_age_staleness_and_rows(store, monkeypatch):
    monkeypatch.setenv("CRM_SNAPSHOT_TTL_HOURS", "12")
    assert crm_status(store, PRESET)["fetched_at"] is None
    store.crm_snapshot_put(BOARD, {"rows": [{"name": "A"}, {"name": "B"}]})
    status = crm_status(store, PRESET)
    assert status["board_rows"] == 2
    assert status["stale"] is False
    assert status["ttl_hours"] == 12.0
