"""Cache keys are stable, and a second lookup of the same org or person costs nothing."""
from __future__ import annotations

import json

from lane_setup import ENRICHED, ORG, FakeApollo

from engine.llm_qa import gemini_cache_key, qa_input
from engine.spend import Meter


def test_org_and_person_lookups_are_free_the_second_time(store, monkeypatch):
    monkeypatch.setenv("APOLLO_MONTHLY_CREDIT_CEILING", "10")
    run = store.create_run(
        kind="discovery", preset_id="underline", vertical_id="concert_series", toggles={}, caps={},
        brief="", started_by="tester", reservation={"apollo": 5},
    )
    store.set_status(run["id"], "enriching", stage=6, stage_name="Enrich")
    apollo = FakeApollo([])
    org_meter = Meter(store, run["id"], "org")
    first, charged = org_meter.org_lookup(apollo, domain="brightcola.com", company="Bright Cola")
    second, again = org_meter.org_lookup(apollo, domain="https://www.brightcola.com", company="Bright Cola")
    assert first["name"] == "Bright Cola"
    assert second == first
    assert charged == 1
    assert again == 0
    assert apollo.calls.count("org") == 1

    enrich_meter = Meter(store, run["id"], "enrich")
    person, person_charged = enrich_meter.enrich(apollo, "p-good")
    _cached, free = enrich_meter.enrich(apollo, "p-good")
    assert person["email"] == ENRICHED["email"]
    assert person_charged == 1
    assert free == 0
    assert store.ledger_run_total(run["id"], "apollo") == 2


def test_gemini_payload_has_no_name_or_email_and_the_key_is_stable():
    lead = {
        "id": "r1",
        "shelf_brand": "Bright Cola",
        "title": "Director of Sponsorships",
        "email": "ann.park@brightcola.com",
        "person": {
            "first_name": "Ann",
            "last_name": "Park",
            "email": "ann.park@brightcola.com",
            "state": "Florida",
            "organization": ORG,
        },
        "evidence": ["Bright Cola official sponsor of a festival"],
    }
    fields = qa_input(lead)
    blob = json.dumps(fields).lower()
    assert "ann" not in blob
    assert "park" not in blob
    assert "@" not in blob
    assert fields["brand"] == "Bright Cola"
    assert fields["person_state"] == "Florida"
    assert gemini_cache_key("concert_series", fields) == gemini_cache_key("concert_series", dict(fields))


def test_spend_json_imports_once(store, tmp_path, monkeypatch):
    from engine.apollo_lane import import_legacy_spend_cache

    path = tmp_path / "concert_spend_cache.json"
    path.write_text(
        json.dumps({"_version": 2, "entries": {"bright cola": {"verdict": "pass", "reason": "disk", "notes": "", "query": ""}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CONCERT_SPEND_CACHE_FILE", str(path))
    assert import_legacy_spend_cache(store) == 1
    assert import_legacy_spend_cache(store) == 0
    hit = store.cache_get("tavily", "spend", "bright cola")
    assert hit["payload"]["verdict"] == "pass"
