"""Approval push: refused until the flag is on, then idempotent. City/State is the person."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from engine.api import create_app
from engine.crm import board_id, new_leads_group_id, validate_board_contract, vertical_labels_for
from engine.presets import PRESETS
from engine.push import PushRefused, push_leads

PRESET = PRESETS["underline"]


def _contract_metadata() -> dict:
    columns = []
    labels = {
        "status": ["Uncontacted", "Contacted"],
        "contact_type": ["Contact"],
        "vertical": vertical_labels_for(PRESET),
    }
    for logical, column_id in PRESET.crm.columns.items():
        names = labels.get(logical, [])
        columns.append(
            {
                "id": column_id,
                "title": logical,
                "settings_str": json.dumps({"labels": [{"name": name} for name in names]}),
            }
        )
    return {
        "name": "The Underline",
        "groups": [{"id": new_leads_group_id(PRESET.crm), "title": "New Leads"}],
        "columns": columns,
    }


class FakeMonday:
    def __init__(self, *, fail: bool = False, emails: list[str] | None = None) -> None:
        self.created: list[dict] = []
        self.fail = fail
        self.meta = _contract_metadata()
        self.emails = emails or []

    def get_board_metadata(self, board_id: int) -> dict:
        return self.meta

    def create_item(self, board_id, group_id, item_name, column_values, create_labels_if_missing=False):
        self.created.append(
            {
                "board_id": board_id,
                "group_id": group_id,
                "item_name": item_name,
                "column_values": column_values,
                "create_labels_if_missing": create_labels_if_missing,
            }
        )
        if self.fail:
            return {"errors": [{"message": "nope"}]}
        return {"data": {"create_item": {"id": f"item-{len(self.created)}"}}}

    def execute_query(self, query, variables=None):
        email_id = PRESET.crm.columns["email"]
        items = [
            {
                "id": str(index),
                "name": "Already",
                "group": {"id": "group"},
                "column_values": [{"id": email_id, "text": email, "value": ""}],
            }
            for index, email in enumerate(self.emails, start=1)
        ]
        return {"data": {"boards": [{"items_page": {"cursor": None, "items": items}}]}}


def _lead(store, run_id: str, *, email: str = "ann.park@brightcola.com", state: str = "approved") -> dict:
    return store.insert_lead(
        run_id,
        state,
        shelf_brand="Bright Cola",
        person_name="Ann Park",
        title="Director of Sponsorships",
        email=email,
        domain="brightcola.com",
        location="Miami, Florida, United States",
        vertical="Concert Series",
        gates=[{"stage": 7, "gate_id": "person_in_florida", "passed": True, "reason": ""}],
        llm={"verdict": "pass", "reason": "paid buyer", "sponsorship_evidence": "yes"},
        evidence=["Bright Cola is an official sponsor."],
        person={
            "enriched": True,
            "first_name": "Ann",
            "last_name": "Park",
            "city": "Miami",
            "state": "Florida",
            "country": "United States",
            "seniority": "director",
            "linkedin": "https://linkedin.com/in/ann",
            "organization": {
                "name": "Bright Cola",
                "website_url": "https://brightcola.com",
                "annual_revenue": 250_000_000,
                "city": "New York",
                "state": "New York",
                "country": "United States",
            },
        },
    )


def _run(store):
    store.crm_snapshot_put(
        board_id(PRESET.crm),
        {"board_id": board_id(PRESET.crm), "rows": []},
    )
    run = store.create_run(
        kind="discovery",
        preset_id="underline",
        vertical_id="concert_series",
        toggles={},
        caps={},
        brief="",
        started_by="lia",
        reservation={},
    )
    store.set_status(run["id"], "needs_review", stage_name="Review")
    return store.get_run(run["id"])


def test_board_contract_names_a_missing_label():
    meta = _contract_metadata()
    for column in meta["columns"]:
        if column["id"] == PRESET.crm.columns["vertical"]:
            column["settings_str"] = json.dumps({"labels": [{"name": "Contact"}]})
    problems = validate_board_contract(meta, PRESET)
    assert any("Concert Series" in problem for problem in problems)


def test_valid_contract_has_no_problems():
    assert validate_board_contract(_contract_metadata(), PRESET) == []


def test_push_is_refused_until_the_flag_is_on(store, monkeypatch):
    monkeypatch.delenv("ENGINE_LIVE_PUSH_ENABLED", raising=False)
    run = _run(store)
    lead = _lead(store, run["id"])
    monday = FakeMonday()
    with pytest.raises(PushRefused, match="ENGINE_LIVE_PUSH_ENABLED"):
        push_leads(store, PRESET, run["id"], actor="lia", monday_factory=lambda: monday)
    assert monday.created == []
    assert store.get_lead(lead["id"])["state"] == "approved"


def test_live_push_stores_the_item_id_and_does_not_create_twice(store, monkeypatch):
    monkeypatch.setenv("ENGINE_LIVE_PUSH_ENABLED", "true")
    notified: list[int] = []
    monkeypatch.setattr(
        "slack_notify.notify_monday_push",
        lambda **kwargs: notified.append(kwargs["contacts_pushed"]) or True,
    )
    run = _run(store)
    lead = _lead(store, run["id"])
    monday = FakeMonday()
    first = push_leads(store, PRESET, run["id"], actor="miguel", monday_factory=lambda: monday)
    assert first["rows"][0]["outcome"] == "created"
    assert first["rows"][0]["monday_item_id"] == "item-1"
    saved = store.get_lead(lead["id"])
    assert saved["state"] == "pushed"
    assert saved["monday_item_id"] == "item-1"
    columns = monday.created[0]["column_values"]
    assert columns[PRESET.crm.columns["city"]] == "Miami"
    assert columns[PRESET.crm.columns["state"]] == "Florida"
    assert columns[PRESET.crm.columns["state"]] != "New York"
    assert monday.created[0]["item_name"] == "Bright Cola"
    assert monday.created[0]["create_labels_if_missing"] is False

    second = push_leads(
        store, PRESET, run["id"], actor="miguel", lead_ids=[lead["id"]], monday_factory=lambda: monday,
    )
    assert second["rows"][0]["outcome"] == "already_pushed"
    assert len(monday.created) == 1
    assert notified == [1]


def test_email_added_since_the_run_started_is_not_created(store, monkeypatch):
    monkeypatch.setenv("ENGINE_LIVE_PUSH_ENABLED", "true")
    run = _run(store)
    lead = _lead(store, run["id"])
    monday = FakeMonday(emails=["ann.park@brightcola.com"])
    result = push_leads(store, PRESET, run["id"], actor="lia", monday_factory=lambda: monday)
    assert result["rows"][0]["outcome"] == "failed"
    assert "already on the board" in result["rows"][0]["reason"]
    assert monday.created == []
    assert store.get_lead(lead["id"])["state"] == "push_failed"


def test_push_endpoint_is_refused_until_the_flag_is_on(store, tmp_path, monkeypatch):
    monkeypatch.delenv("ENGINE_LIVE_PUSH_ENABLED", raising=False)
    app = create_app(db_path=store.path, start_worker=False, load_env=False, dist_dir=tmp_path)
    with TestClient(app) as client:
        run = _run(client.app.state.store)
        _lead(client.app.state.store, run["id"])
        res = client.post(f"/api/runs/{run['id']}/push", json={})
    assert res.status_code == 409
    assert "ENGINE_LIVE_PUSH_ENABLED" in res.json()["detail"]
