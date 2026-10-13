"""A paid call that would pass the reservation stops the run and keeps the leads."""
from __future__ import annotations

from lane_setup import GOOD, FakeApollo, gemini_pass, queue, seed, tavily_pass

from engine import apollo_lane, llm_qa
from engine.pipeline import execute_run
from engine.spend import BudgetStop, Meter, StageGuard


def test_org_lookup_stops_on_the_reservation_before_the_http_call(store, monkeypatch, tmp_path):
    seed(store, monkeypatch, tmp_path)
    apollo = FakeApollo([GOOD])
    monkeypatch.setattr(apollo_lane, "apollo_factory", lambda: apollo)
    monkeypatch.setattr(apollo_lane, "tavily_factory", tavily_pass)
    monkeypatch.setattr(llm_qa, "generate_batch", gemini_pass)
    run = queue(store, "concert_series")
    store.update_run(run["id"], reservation={"apollo": 0, "tavily": 5, "gemini": 5})
    assert execute_run(store, store.claim_next_queued()) == "budget_stopped"
    saved = store.get_run(run["id"])
    assert saved["status"] == "budget_stopped"
    assert "reservation" in saved["error"]
    assert "org" not in apollo.calls
    assert store.list_leads(run["id"])[0]["state"] == "candidate"


def test_enrich_refuses_unless_the_run_is_enriching(store):
    run = store.create_run(
        kind="discovery", preset_id="underline", vertical_id="concert_series", toggles={}, caps={},
        brief="", started_by="tester", reservation={"apollo": 5},
    )
    store.set_status(run["id"], "running", stage=6, stage_name="Enrich")
    meter = Meter(store, run["id"], "enrich")
    try:
        meter.enrich(FakeApollo([GOOD]), "p-good")
        raised = False
    except StageGuard:
        raised = True
    assert raised is True


def test_meter_charge_names_the_provider(store):
    run = store.create_run(
        kind="discovery", preset_id="underline", vertical_id="concert_series", toggles={}, caps={},
        brief="", started_by="tester", reservation={"apollo": 0},
    )
    meter = Meter(store, run["id"], "org")
    try:
        meter._can_charge("apollo", 1)
        raised = None
    except BudgetStop as exc:
        raised = exc
    assert raised is not None and raised.provider == "apollo"
