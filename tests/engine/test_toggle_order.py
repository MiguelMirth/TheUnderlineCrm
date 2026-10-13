"""Paid calls happen only after the free gates, and enrich waits for the shortlist pause."""
from __future__ import annotations

from lane_setup import BAD, GOOD, PLANNER, FakeApollo, gemini_pass, queue, seed, tavily_pass

from engine import apollo_lane, llm_qa
from engine.pipeline import execute_run


def _bind(monkeypatch, apollo: FakeApollo, gemini=gemini_pass, tavily=tavily_pass):
    monkeypatch.setattr(apollo_lane, "apollo_factory", lambda: apollo)
    monkeypatch.setattr(apollo_lane, "tavily_factory", tavily)
    monkeypatch.setattr(llm_qa, "generate_batch", gemini)


def test_concert_pays_only_after_free_gates_and_pauses_before_enrich(store, monkeypatch, tmp_path):
    seed(store, monkeypatch, tmp_path)
    apollo = FakeApollo([BAD, GOOD])
    calls: list[str] = []

    def tavily(query: str) -> dict:
        calls.append("tavily")
        return tavily_pass(query)

    def gemini(vertical_id: str, rows: list[dict]) -> list[dict]:
        calls.append("gemini")
        assert rows and "ann.park@" not in str(rows).lower()
        assert "park" not in rows[0]["brand"].lower()
        return gemini_pass(vertical_id, rows)

    _bind(monkeypatch, apollo, gemini, tavily)
    run = queue(store, "concert_series")
    assert execute_run(store, store.claim_next_queued()) == "awaiting_enrich"

    assert apollo.calls[0] == "people"
    assert "org" in apollo.calls
    assert apollo.calls.index("org") > apollo.calls.index("people")
    assert "enrich" not in apollo.calls
    assert calls == ["tavily", "gemini"]
    assert apollo.calls.index("org") < len(apollo.calls)  # org happened before the pause
    # Tavily and Gemini are recorded after the org lookup, never before people search.
    assert calls[0] == "tavily"

    by_id = {lead["person"]["apollo_id"]: lead for lead in store.list_leads(run["id"])}
    assert by_id["p-bad"]["state"] == "qa_failed"
    assert by_id["p-good"]["state"] == "shortlisted"
    assert any(gate["gate_id"] == "spend_evidence" and gate["passed"] for gate in by_id["p-good"]["gates"])
    assert store.get_run(run["id"])["status"] == "awaiting_enrich"


def test_rejected_shortlist_is_not_enriched(store, monkeypatch, tmp_path):
    seed(store, monkeypatch, tmp_path)
    apollo = FakeApollo([GOOD])
    _bind(monkeypatch, apollo)
    run = queue(store, "concert_series")
    execute_run(store, store.claim_next_queued())
    lead = store.list_leads(run["id"])[0]
    store.update_lead(lead["id"], state="rejected", prior_state="shortlisted")
    store.set_status(run["id"], "queued", stage=6, stage_name="Enrich")
    execute_run(store, store.claim_next_queued())
    assert "enrich" not in apollo.calls
    assert store.get_lead(lead["id"])["state"] == "rejected"


def test_enrich_runs_only_for_the_shortlist_then_post_gates(store, monkeypatch, tmp_path):
    seed(store, monkeypatch, tmp_path)
    apollo = FakeApollo([BAD, GOOD])
    _bind(monkeypatch, apollo)
    run = queue(store, "concert_series")
    execute_run(store, store.claim_next_queued())
    store.set_status(run["id"], "queued", stage=6, stage_name="Enrich")
    assert execute_run(store, store.claim_next_queued()) == "needs_review"
    assert apollo.calls.count("enrich") == 1
    good = next(lead for lead in store.list_leads(run["id"]) if lead["person"]["apollo_id"] == "p-good")
    bad = next(lead for lead in store.list_leads(run["id"]) if lead["person"]["apollo_id"] == "p-bad")
    assert good["state"] == "needs_review"
    assert good["email"] == "ann.park@brightcola.com"
    assert good["person"]["enriched"] is True
    assert bad["state"] == "qa_failed"
    from engine.gates import approvable

    assert approvable(good) == (True, "ok")


def test_a_known_bad_industry_does_not_buy_an_org(store, monkeypatch, tmp_path):
    seed(store, monkeypatch, tmp_path)
    person = {
        "id": "p-it",
        "first_name": "Sam",
        "last_name_obfuscated": "Le***",
        "title": "Vice President of Marketing",
        "state": "Florida",
        "country": "United States",
        "organization": {
            "name": "CargoSprint",
            "primary_domain": "cargosprint.com",
            "industry": "information technology & services",
        },
    }
    apollo = FakeApollo([person])
    _bind(monkeypatch, apollo)
    run = queue(store, "concert_series")
    execute_run(store, store.claim_next_queued())
    assert "org" not in apollo.calls
    lead = store.list_leads(run["id"])[0]
    assert lead["state"] == "qa_failed"
    assert any(gate["gate_id"] == "concert_org_viable" and not gate["passed"] for gate in lead["gates"])
    seed(store, monkeypatch, tmp_path)
    apollo = FakeApollo([PLANNER])
    calls: list[str] = []
    _bind(monkeypatch, apollo, tavily=lambda query: calls.append("tavily") or {})
    run = queue(store, "venue_rental")
    assert execute_run(store, store.claim_next_queued()) == "awaiting_enrich"
    assert "org" not in apollo.calls
    assert calls == []
    assert "gemini" not in apollo.calls
    lead = store.list_leads(run["id"])[0]
    assert lead["state"] == "shortlisted"
    assert lead["llm"]["verdict"] == "pass"
