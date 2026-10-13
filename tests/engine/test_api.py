"""HTTP contract: health, presets, estimate, run lifecycle, leads, and the UI fallback."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.api import create_app
from engine.crm import board_id
from engine.presets import PRESETS
from engine.store import SCHEMA_VERSION


def _dist(tmp_path: Path, with_index: bool = True) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    if with_index:
        (dist / "index.html").write_text("<html>shell</html>", encoding="utf-8")
        (dist / "assets").mkdir()
        (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return dist


def seed_fresh_crm(store) -> None:
    """A snapshot read a moment ago, so Start is not blocked on Monday in tests."""
    preset = PRESETS["underline"]
    store.crm_snapshot_put(board_id(preset.crm), {"board_id": board_id(preset.crm), "rows": []})


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "engine.db"), start_worker=False, load_env=False, dist_dir=_dist(tmp_path))
    with TestClient(app) as c:
        seed_fresh_crm(c.app.state.store)
        yield c


def _sponsor_body(**overrides):
    body = {"preset_id": "underline", "vertical_id": "sponsor_brands", "toggles": {}, "caps": {}}
    body.update(overrides)
    return body


def _ceilings(monkeypatch):
    for name in ("APOLLO_MONTHLY_CREDIT_CEILING", "TAVILY_MONTHLY_CREDIT_CEILING", "CURSOR_MONTHLY_RUN_CEILING", "GEMINI_MONTHLY_REQUEST_CEILING"):
        monkeypatch.setenv(name, "5000")


def test_health_reports_schema_worker_and_ui(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["ui_built"] is True
    assert body["worker_alive"] is False  # start_worker=False in this fixture


def test_presets_list_and_problem_check(client):
    presets = client.get("/api/presets").json()
    assert [p["id"] for p in presets] == ["underline"]
    assert client.get("/api/presets/underline/problems").json() == []
    assert client.get("/api/presets/nope").status_code == 404


def test_estimate_is_blocked_without_ceilings(client):
    est = client.post("/api/estimate", json=_sponsor_body()).json()
    assert est["can_start"] is False
    assert est["blockers"]
    apollo = next(p for p in est["providers"] if p["provider"] == "apollo")
    assert apollo["total"] == 40
    assert apollo["ceiling"] is None


def test_estimate_toggle_states_are_labelled(client):
    est = client.post("/api/estimate", json=_sponsor_body(toggles={"min_confidence": 70})).json()
    state = next(t for t in est["toggles"] if t["id"] == "min_confidence")
    assert state["value"] == 70
    assert state["status"] == "relaxed"


def test_start_is_refused_with_blockers_when_ceiling_missing(client):
    res = client.post("/api/runs", json=_sponsor_body())
    assert res.status_code == 409
    assert res.json()["detail"]["blockers"]


def test_start_creates_a_queued_run_with_actor(client, monkeypatch):
    _ceilings(monkeypatch)
    res = client.post(
        "/api/runs",
        json=_sponsor_body(toggles={"florida_person_only": False}, brief="Miami art week"),
        headers={"Cf-Access-Authenticated-User-Email": "lia@knowyourmirth.com"},
    )
    assert res.status_code == 201
    run = res.json()
    assert run["status"] == "queued"  # the worker is off in this fixture
    assert run["started_by"] == "lia@knowyourmirth.com"
    assert run["brief"] == "Miami art week"
    toggle = next(t for t in run["toggles"] if t["id"] == "florida_person_only")
    assert toggle["status"] == "relaxed"
    assert run["reservation"]["apollo"] == 40


def test_start_rejects_unknown_toggle_with_422(client, monkeypatch):
    _ceilings(monkeypatch)
    res = client.post("/api/runs", json=_sponsor_body(toggles={"made_up": True}))
    assert res.status_code == 422


def test_start_rejects_unknown_cap_with_422(client, monkeypatch):
    _ceilings(monkeypatch)
    res = client.post("/api/runs", json=_sponsor_body(caps={"nonsense": 1}))
    assert res.status_code == 422


def test_unknown_vertical_is_404(client):
    res = client.post("/api/estimate", json=_sponsor_body(vertical_id="nope"))
    assert res.status_code == 404


def test_get_list_events_and_leads_for_a_run(client, monkeypatch):
    _ceilings(monkeypatch)
    created = client.post("/api/runs", json=_sponsor_body(vertical_id="venue_rental")).json()
    run_id = created["id"]
    assert client.get(f"/api/runs/{run_id}").json()["id"] == run_id
    assert any(r["id"] == run_id for r in client.get("/api/runs").json())
    assert client.get(f"/api/runs/{run_id}/events").status_code == 200
    assert client.get(f"/api/runs/{run_id}/leads").json() == []
    assert client.get("/api/runs/r_missing1").status_code == 404


def test_lead_is_not_approvable_without_gates_and_llm(client, monkeypatch):
    _ceilings(monkeypatch)
    run_id = client.post("/api/runs", json=_sponsor_body()).json()["id"]
    client.app.state.store.insert_lead(run_id, "needs_review", email="a@x.com", gates=[])
    lead = client.get(f"/api/runs/{run_id}/leads").json()[0]
    assert lead["approvable"] is False
    assert lead["approve_blocker"] == "LLM QA missing"


def test_resume_refuses_a_queued_run(client, monkeypatch):
    _ceilings(monkeypatch)
    run_id = client.post("/api/runs", json=_sponsor_body()).json()["id"]
    assert client.post(f"/api/runs/{run_id}/resume").status_code == 409


def test_delete_refuses_a_queued_run_and_removes_a_finished_one(client, monkeypatch):
    _ceilings(monkeypatch)
    run_id = client.post("/api/runs", json=_sponsor_body()).json()["id"]
    refused = client.delete(f"/api/runs/{run_id}")
    assert refused.status_code == 409
    assert client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.delete("/api/runs/r_missing1").status_code == 404


def test_removed_vertical_still_lists(client):
    run = client.app.state.store.create_run(
        kind="discovery",
        preset_id="underline",
        vertical_id="park_adjacent",
        toggles={},
        caps={},
        brief="",
        started_by="tester",
        reservation={},
    )
    row = next(item for item in client.get("/api/runs").json() if item["id"] == run["id"])
    assert row["vertical_label"] == "Park-adjacent"
    assert row["toggles"] == []


def test_park_adjacent_cannot_be_started(client):
    assert client.post("/api/estimate", json=_sponsor_body(vertical_id="park_adjacent")).status_code == 404


def test_preset_settings_override_search_board_and_gate_defaults(client):
    settings = client.get("/api/presets/underline/settings").json()
    concert = next(vertical for vertical in settings["verticals"] if vertical["id"] == "concert_series")
    assert "Sponsorship" in concert["titles"]
    assert len(settings["verticals"]) == 3
    concert["titles"] = ["Chief Brand Officer"]
    gate = next(toggle for toggle in concert["toggles"] if toggle["id"] == "florida_person_only")
    assert gate["code_default"] is True
    gate["value"] = False
    settings["board_id"] = "999001"
    saved = client.put("/api/presets/underline/settings", json=settings)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["board_id"] == "999001"
    saved_concert = next(vertical for vertical in body["verticals"] if vertical["id"] == "concert_series")
    assert saved_concert["titles"] == ["Chief Brand Officer"]
    assert next(toggle for toggle in saved_concert["toggles"] if toggle["id"] == "florida_person_only")["code_default"] is True
    preset = client.get("/api/presets/underline").json()
    preset_concert = next(vertical for vertical in preset["verticals"] if vertical["id"] == "concert_series")
    assert preset_concert["source"]["params"]["titles"] == ["Chief Brand Officer"]
    florida = next(toggle for toggle in preset_concert["toggles"] if toggle["id"] == "florida_person_only")
    assert florida["default"] is False
    assert client.get("/api/crm/status").json()["board_id"] == "999001"

    broken = client.get("/api/presets/underline/settings").json()
    next(vertical for vertical in broken["verticals"] if vertical["id"] == "concert_series")["titles"] = []
    assert client.put("/api/presets/underline/settings", json=broken).status_code == 422

    reset = client.post("/api/presets/underline/settings/reset")
    assert reset.status_code == 200
    restored = reset.json()
    assert restored["board_id"] == "18401545002"
    restored_concert = next(vertical for vertical in restored["verticals"] if vertical["id"] == "concert_series")
    assert "Sponsorship" in restored_concert["titles"]
    assert client.get("/api/crm/status").json()["board_id"] == "18401545002"


def test_cancel_queued_run(client, monkeypatch):
    _ceilings(monkeypatch)
    run_id = client.post("/api/runs", json=_sponsor_body()).json()["id"]
    res = client.post(f"/api/runs/{run_id}/cancel")
    assert res.json()["status"] == "cancelled"


def test_unknown_api_path_is_404_not_the_ui(client):
    res = client.get("/api/does-not-exist")
    assert res.status_code == 404
    assert "shell" not in res.text


def test_ui_root_and_deep_link_serve_the_shell(client):
    assert "shell" in client.get("/").text
    assert "shell" in client.get("/runs/r_abc123").text


def test_built_assets_are_served(client):
    res = client.get("/assets/app.js")
    assert res.status_code == 200
    assert "console.log" in res.text


def test_ui_not_built_returns_503_with_instructions(tmp_path):
    app = create_app(db_path=str(tmp_path / "e.db"), start_worker=False, load_env=False, dist_dir=_dist(tmp_path, with_index=False))
    with TestClient(app) as c:
        res = c.get("/")
        assert res.status_code == 503
        assert "npm --prefix web run build" in res.text
        assert c.get("/api/health").json()["ui_built"] is False


def test_path_traversal_does_not_leak_files_outside_dist(tmp_path):
    dist = _dist(tmp_path)
    (tmp_path / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
    app = create_app(db_path=str(tmp_path / "e.db"), start_worker=False, load_env=False, dist_dir=dist)
    with TestClient(app) as c:
        for path in ("/%2e%2e/secret.txt", "/..%2fsecret.txt", "/assets/..%2f..%2fsecret.txt"):
            assert "TOP-SECRET" not in c.get(path).text


# -- CRM status, refresh, and decisions --------------------------------------

def test_start_is_blocked_by_missing_crm_even_with_ceilings(tmp_path, monkeypatch):
    monkeypatch.delenv("MONDAY_API_KEY", raising=False)
    _ceilings(monkeypatch)
    app = create_app(db_path=str(tmp_path / "e.db"), start_worker=False, load_env=False, dist_dir=_dist(tmp_path))
    with TestClient(app) as c:
        est = c.post("/api/estimate", json=_sponsor_body()).json()
        assert est["can_start"] is False
        assert any("MONDAY_API_KEY" in b for b in est["blockers"])


def test_crm_status_reports_the_snapshot(client):
    status = client.get("/api/crm/status").json()
    assert status["board_id"] == "18401545002"
    assert status["stale"] is False
    assert status["fetched_at"] is not None


class _FakeMonday:
    def __init__(self):
        self.calls = 0

    def execute_query(self, query, variables=None):
        self.calls += 1
        return {
            "data": {
                "boards": [
                    {
                        "items_page": {
                            "cursor": None,
                            "items": [
                                {
                                    "id": "1",
                                    "name": "Acme Foods",
                                    "group": {"id": "group_mm0xbmrj"},
                                    "column_values": [
                                        {"id": "email_mm0xb00t", "text": "jane@acme.com", "value": ""},
                                    ],
                                }
                            ],
                        }
                    }
                ]
            }
        }


def test_refresh_reads_the_board_through_the_injected_client(tmp_path):
    fake = _FakeMonday()
    app = create_app(
        db_path=str(tmp_path / "e.db"),
        start_worker=False,
        load_env=False,
        dist_dir=_dist(tmp_path),
        monday_factory=lambda: fake,
    )
    with TestClient(app) as c:
        status = c.post("/api/crm/refresh").json()
        assert fake.calls == 1
        assert status["board_rows"] == 1
        assert status["stale"] is False


def test_refresh_is_refused_while_a_run_is_live(client, monkeypatch):
    _ceilings(monkeypatch)
    client.post("/api/runs", json=_sponsor_body())  # queued, worker is off
    res = client.post("/api/crm/refresh")
    assert res.status_code == 409
    assert "A run is live" in res.json()["detail"]


def test_approve_returns_409_with_every_refused_reason(client, monkeypatch):
    _ceilings(monkeypatch)
    run_id = client.post("/api/runs", json=_sponsor_body()).json()["id"]
    client.app.state.store.insert_lead(run_id, "needs_review", email="a@x.com", gates=[], person={"enriched": True})
    lead_id = client.get(f"/api/runs/{run_id}/leads").json()[0]["id"]
    res = client.post(f"/api/runs/{run_id}/leads/decide", json={"action": "approve", "lead_ids": [lead_id]})
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["refused"][0]["reason"] == "LLM QA missing"
    assert client.get(f"/api/runs/{run_id}/leads").json()[0]["state"] == "needs_review"


def test_reject_and_restore_over_the_api(client, monkeypatch):
    _ceilings(monkeypatch)
    run_id = client.post("/api/runs", json=_sponsor_body()).json()["id"]
    client.app.state.store.insert_lead(run_id, "needs_review", email="a@x.com", gates=[], person={"enriched": True})
    lead_id = client.get(f"/api/runs/{run_id}/leads").json()[0]["id"]
    rejected = client.post(f"/api/runs/{run_id}/leads/decide", json={"action": "reject", "lead_ids": [lead_id]})
    assert rejected.json()["updated"] == [lead_id]
    restored = client.post(f"/api/runs/{run_id}/leads/decide", json={"action": "restore", "lead_ids": [lead_id]})
    assert restored.json()["updated"] == [lead_id]
    assert client.get(f"/api/runs/{run_id}/leads").json()[0]["state"] == "needs_review"


def test_decide_refuses_an_empty_selection(client, monkeypatch):
    _ceilings(monkeypatch)
    run_id = client.post("/api/runs", json=_sponsor_body()).json()["id"]
    res = client.post(f"/api/runs/{run_id}/leads/decide", json={"action": "reject", "lead_ids": []})
    assert res.status_code == 422


def test_restored_shortlist_can_be_enriched_after_review(client, monkeypatch):
    _ceilings(monkeypatch)
    run_id = client.post("/api/runs", json=_sponsor_body()).json()["id"]
    store = client.app.state.store
    store.set_status(run_id, "needs_review", stage=7, stage_name="Review")
    store.insert_lead(run_id, "shortlisted", email="a@x.com", shelf_brand="Yardi", person={"apollo_id": "p1"})
    res = client.post(f"/api/runs/{run_id}/enrich")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "queued"
    assert body["stage"] == 6
    assert body["counts"]["shortlisted"] == 1


def test_enrich_refuses_review_when_nothing_is_shortlisted(client, monkeypatch):
    _ceilings(monkeypatch)
    run_id = client.post("/api/runs", json=_sponsor_body()).json()["id"]
    client.app.state.store.set_status(run_id, "needs_review", stage=7, stage_name="Review")
    res = client.post(f"/api/runs/{run_id}/enrich")
    assert res.status_code == 409
    assert "shortlisted" in res.json()["detail"]
