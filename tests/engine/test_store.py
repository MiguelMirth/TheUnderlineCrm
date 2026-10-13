"""SQLite store: schema versioning, FIFO claim, interrupted recovery, leads, ledger, cache, backup."""
from __future__ import annotations

import sqlite3

import pytest

from engine.store import SCHEMA_VERSION, RunInProgress, SchemaTooNew, Store


def _make_run(store: Store, *, reservation: dict[str, float] | None = None, vertical: str = "venue_rental") -> str:
    run = store.create_run(
        kind="discovery",
        preset_id="underline",
        vertical_id=vertical,
        toggles={"florida_person_only": True},
        caps={"target": 10},
        brief="",
        started_by="tester",
        reservation=reservation or {},
    )
    return run["id"]


def test_schema_is_created_at_current_version(store: Store):
    assert store.schema_version() == SCHEMA_VERSION


def test_reopening_does_not_reapply_schema(store: Store):
    run_id = _make_run(store)
    reopened = Store(store.path)
    assert reopened.schema_version() == SCHEMA_VERSION
    assert reopened.get_run(run_id) is not None


def test_newer_schema_is_refused(tmp_path):
    path = str(tmp_path / "future.db")
    Store(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 1,))
    conn.commit()
    conn.close()
    with pytest.raises(SchemaTooNew):
        Store(path)


def test_run_ids_are_short_and_url_safe(store: Store):
    run_id = _make_run(store)
    assert run_id.startswith("r_")
    assert len(run_id) == 8
    assert run_id.replace("_", "").isalnum()


def test_claim_is_fifo_and_marks_running(store: Store):
    first = _make_run(store)
    second = _make_run(store)
    claimed = store.claim_next_queued()
    assert claimed["id"] == first
    assert claimed["status"] == "running"
    assert store.claim_next_queued()["id"] == second
    assert store.claim_next_queued() is None


def test_recover_interrupted_marks_live_runs(store: Store):
    run_id = _make_run(store)
    store.claim_next_queued()  # now running
    assert store.recover_interrupted() == 1
    run = store.get_run(run_id)
    assert run["status"] == "interrupted"
    assert "Process stopped" in run["error"]


def test_resume_requeues_only_resumable_runs(store: Store):
    run_id = _make_run(store)
    store.claim_next_queued()
    store.recover_interrupted()
    resumed = store.queue_resume(run_id)
    assert resumed["status"] == "queued"
    assert resumed["error"] == ""


def test_resume_does_not_touch_a_finished_run(store: Store):
    run_id = _make_run(store)
    store.set_status(run_id, "complete", stage_name="Done")
    assert store.queue_resume(run_id)["status"] == "complete"


def test_cancel_queued_run_is_immediate(store: Store):
    run_id = _make_run(store)
    assert store.request_cancel(run_id)["status"] == "cancelled"


def test_cancel_running_run_sets_flag_and_keeps_status(store: Store):
    run_id = _make_run(store)
    store.claim_next_queued()
    run = store.request_cancel(run_id)
    assert run["status"] == "running"
    assert run["cancel_requested"] is True


def test_update_run_refuses_unknown_column(store: Store):
    run_id = _make_run(store)
    with pytest.raises(KeyError):
        store.update_run(run_id, not_a_column="x")


def test_events_are_kept_in_order(store: Store):
    run_id = _make_run(store)
    store.add_event(run_id, "info", "one")
    store.add_event(run_id, "warn", "two")
    messages = [e["message"] for e in store.list_events(run_id)]
    assert messages[-2:] == ["one", "two"]


def test_leads_insert_list_update_and_count(store: Store):
    run_id = _make_run(store)
    a = store.insert_lead(run_id, "candidate", email="a@x.com", person={"enriched": False}, gates=[])
    b = store.insert_lead(
        run_id,
        "needs_review",
        email="b@x.com",
        gates=[{"stage": 1, "gate_id": "title_gate", "passed": True, "reason": ""}],
        llm={"verdict": "pass"},
    )
    assert a["id"] == f"{run_id}-0001"
    assert b["seq"] == 2
    assert store.count_leads(run_id) == {"candidate": 1, "needs_review": 1}
    assert [r["id"] for r in store.list_leads(run_id, ["needs_review"])] == [b["id"]]
    store.update_lead(a["id"], state="rejected", decided_by="lia@x.com")
    assert store.get_lead(a["id"])["state"] == "rejected"


def test_update_lead_refuses_unknown_column(store: Store):
    run_id = _make_run(store)
    lead = store.insert_lead(run_id, "candidate")
    with pytest.raises(KeyError):
        store.update_lead(lead["id"], email_x="nope")


def test_ledger_totals_by_month_and_provider(store: Store):
    run_id = _make_run(store)
    store.ledger_append(provider="apollo", units=10, month="2026-10", run_id=run_id, stage="enrich")
    store.ledger_append(provider="apollo", units=4, month="2026-10", run_id=run_id, stage="org")
    store.ledger_append(provider="apollo", units=3, month="2026-09", run_id=None, stage="org")
    store.ledger_append(provider="apollo", units=1, month="2026-10", run_id=run_id, stage="org", kind="refund")
    assert store.ledger_total("apollo", "2026-10") == 13
    assert store.ledger_total("apollo", "2026-09") == 3
    assert store.ledger_total("tavily", "2026-10") == 0
    assert store.ledger_run_total(run_id, "apollo") == 13


def test_reserved_counts_only_active_runs(store: Store):
    active = _make_run(store, reservation={"apollo": 40})
    done = _make_run(store, reservation={"apollo": 99})
    store.set_status(done, "complete")
    assert store.reserved_total("apollo") == 40
    store.set_status(active, "complete")
    assert store.reserved_total("apollo") == 0


def test_api_cache_put_overwrites_and_reads_back(store: Store):
    store.cache_put("apollo", "org", "dom:acme.com", {"name": "Acme"}, units=1)
    store.cache_put("apollo", "org", "dom:acme.com", {"name": "Acme Inc"}, units=1)
    hit = store.cache_get("apollo", "org", "dom:acme.com")
    assert hit["payload"] == {"name": "Acme Inc"}
    assert hit["units"] == 1
    assert store.cache_get("apollo", "org", "dom:missing.com") is None


def test_crm_snapshot_round_trip(store: Store):
    store.crm_snapshot_put("18401545002", {"emails": ["a@x.com"]})
    snap = store.crm_snapshot_get("18401545002")
    assert snap["payload"] == {"emails": ["a@x.com"]}
    assert store.crm_snapshot_get("999") is None


def test_backup_is_a_readable_copy(store: Store, tmp_path):
    run_id = _make_run(store)
    dest = str(tmp_path / "backups" / "copy.db")
    store.backup_to(dest)
    copy = Store(dest)
    assert copy.get_run(run_id) is not None


def test_daily_backup_is_once_per_day_and_prunes(store: Store, tmp_path):
    from engine.store import write_daily_backup

    db = str(tmp_path / "underline.db")
    store.backup_to(db)
    live = Store(db)
    _make_run(live)
    first = write_daily_backup(live, db, day="2026-10-01", keep=2)
    again = write_daily_backup(live, db, day="2026-10-01", keep=2)
    write_daily_backup(live, db, day="2026-10-02", keep=2)
    write_daily_backup(live, db, day="2026-10-03", keep=2)
    names = sorted(p.name for p in (tmp_path / "backups").glob("underline-*.db"))
    assert first is not None and again is None
    assert names == ["underline-2026-10-02.db", "underline-2026-10-03.db"]


def test_delete_run_removes_leads_and_refuses_a_live_status(store: Store):
    run_id = _make_run(store)
    store.insert_lead(run_id, "needs_review", email="a@x.com")
    store.add_event(run_id, "info", "hello")
    store.set_status(run_id, "running")
    with pytest.raises(RunInProgress):
        store.delete_run(run_id)
    assert store.get_run(run_id) is not None
    store.set_status(run_id, "complete")
    assert store.delete_run(run_id) is True
    assert store.get_run(run_id) is None
    assert store.list_leads(run_id) == []
    assert store.list_events(run_id) == []
    assert store.delete_run(run_id) is False


def test_v2_database_gains_preset_settings(tmp_path):
    path = str(tmp_path / "v2.db")
    Store(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE preset_settings")
        conn.execute("UPDATE schema_version SET version = 2")
    upgraded = Store(path)
    assert upgraded.schema_version() == SCHEMA_VERSION
    upgraded.put_preset_settings("underline", {"board_id": "42"})
    assert upgraded.get_preset_settings("underline") == {"board_id": "42"}
