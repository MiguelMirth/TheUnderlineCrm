"""Worker and stage execution: no-op path, failure visibility, budget stop, checkpoints, and the real thread."""
from __future__ import annotations

import time

from engine import pipeline
from engine.pipeline import RunWorker, execute_run
from engine.spend import BudgetStop


def _queue(store, vertical: str = "sponsor_brands") -> str:
    run = store.create_run(
        kind="discovery",
        preset_id="underline",
        vertical_id=vertical,
        toggles={},
        caps={},
        brief="",
        started_by="tester",
        reservation={},
    )
    return run["id"]


def test_noop_source_completes_with_no_leads(store, monkeypatch):
    monkeypatch.setattr(pipeline, "handler_for", lambda store, run: pipeline._noop_source)
    run_id = _queue(store)
    worker = RunWorker(store)
    assert worker.run_once() is True
    run = store.get_run(run_id)
    assert run["status"] == "complete"
    messages = [e["message"] for e in store.list_events(run_id)]
    assert any("exercised the queue only" in m for m in messages)


def test_empty_queue_returns_false(store):
    assert RunWorker(store).run_once() is False


def test_run_with_leads_ends_in_review(store, monkeypatch):
    def source(store_, run):
        store_.insert_lead(run["id"], "needs_review", email="a@x.com", gates=[], llm={"verdict": "pass"})
        return "1 lead"

    monkeypatch.setitem(pipeline.SOURCE_HANDLERS, "venue_rental", source)
    run_id = _queue(store, "venue_rental")
    execute_run(store, store.claim_next_queued())
    assert store.get_run(run_id)["status"] == "needs_review"


def test_failure_is_visible_with_stage_and_message(store, monkeypatch):
    def broken(store_, run):
        raise RuntimeError("Apollo returned 500")

    monkeypatch.setitem(pipeline.SOURCE_HANDLERS, "venue_rental", broken)
    run_id = _queue(store, "venue_rental")
    execute_run(store, store.claim_next_queued())
    run = store.get_run(run_id)
    assert run["status"] == "error"
    assert run["error"] == "Source: Apollo returned 500"
    assert any(e["level"] == "error" for e in store.list_events(run_id))


def test_budget_stop_keeps_the_run_reviewable(store, monkeypatch):
    def stops(store_, run):
        store_.insert_lead(run["id"], "needs_review", email="a@x.com", gates=[], llm={"verdict": "pass"})
        raise BudgetStop("apollo", "apollo reservation exhausted")

    monkeypatch.setitem(pipeline.SOURCE_HANDLERS, "venue_rental", stops)
    run_id = _queue(store, "venue_rental")
    execute_run(store, store.claim_next_queued())
    run = store.get_run(run_id)
    assert run["status"] == "budget_stopped"
    assert store.count_leads(run_id) == {"needs_review": 1}


def test_cancel_flag_before_start_is_honored(store):
    run_id = _queue(store)
    claimed = store.claim_next_queued()
    store.update_run(run_id, cancel_requested=True)
    claimed = store.get_run(run_id)
    assert execute_run(store, claimed) == "cancelled"


def test_resume_reenters_the_saved_stage(store, monkeypatch):
    monkeypatch.setattr(pipeline, "handler_for", lambda store, run: pipeline._noop_source)
    run_id = _queue(store)
    store.claim_next_queued()
    store.set_status(run_id, "interrupted", stage=3, stage_name="Firmographics")
    store.queue_resume(run_id)
    RunWorker(store).run_once()
    run = store.get_run(run_id)
    assert run["status"] == "complete"
    assert any("Started at stage 3" in e["message"] for e in store.list_events(run_id))


def test_worker_thread_processes_queue_and_stops(store, monkeypatch):
    monkeypatch.setattr(pipeline, "handler_for", lambda store, run: pipeline._noop_source)
    run_id = _queue(store)
    worker = RunWorker(store, poll_s=0.05)
    worker.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and store.get_run(run_id)["status"] not in ("complete", "error"):
            time.sleep(0.05)
        assert store.get_run(run_id)["status"] == "complete"
        assert worker.alive
    finally:
        worker.stop()
    assert not worker.alive
