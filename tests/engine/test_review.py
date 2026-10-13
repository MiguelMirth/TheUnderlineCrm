"""Operator decisions: approve is all-or-nothing, reject and restore apply where they can, and the LLM rule holds."""
from __future__ import annotations

from engine.review import decide

PASSING = [{"stage": 1, "gate_id": "title_gate", "passed": True, "reason": ""}]
FAILING = [{"stage": 1, "gate_id": "title_gate", "passed": False, "reason": "title: intern"}]


def _run(store) -> str:
    run = store.create_run(
        kind="discovery",
        preset_id="underline",
        vertical_id="venue_rental",
        toggles={},
        caps={},
        brief="",
        started_by="tester",
        reservation={},
    )
    return run["id"]


def _lead(store, run_id, *, email, gates=PASSING, llm=None, enriched=True, state="needs_review"):
    return store.insert_lead(
        run_id,
        state,
        email=email,
        gates=gates,
        llm=llm,
        person={"enriched": enriched},
    )


def test_approve_refuses_a_lead_without_an_llm_verdict_and_writes_nothing(store):
    run_id = _run(store)
    lead = _lead(store, run_id, email="a@x.com", llm=None)
    result = decide(store, run_id, "approve", [lead["id"]], "lia@x.com")
    assert result["updated"] == []
    assert result["refused"] == [{"lead_id": lead["id"], "reason": "LLM QA missing"}]
    assert store.get_lead(lead["id"])["state"] == "needs_review"


def test_approve_is_all_or_nothing(store):
    run_id = _run(store)
    good = _lead(store, run_id, email="good@x.com", llm={"verdict": "pass"})
    bad = _lead(store, run_id, email="bad@x.com", llm={"verdict": "fail"})
    result = decide(store, run_id, "approve", [good["id"], bad["id"]], "lia@x.com")
    assert result["updated"] == []
    assert len(result["refused"]) == 1
    assert store.get_lead(good["id"])["state"] == "needs_review"


def test_approve_records_who_and_keeps_the_prior_state(store):
    run_id = _run(store)
    lead = _lead(store, run_id, email="a@x.com", llm={"verdict": "flag"})
    result = decide(store, run_id, "approve", [lead["id"]], "lia@x.com")
    assert result["updated"] == [lead["id"]]
    saved = store.get_lead(lead["id"])
    assert saved["state"] == "approved"
    assert saved["decided_by"] == "lia@x.com"
    assert saved["prior_state"] == "needs_review"
    assert saved["decided_at"]


def test_reject_then_restore_returns_to_the_prior_state(store):
    run_id = _run(store)
    lead = _lead(store, run_id, email="a@x.com", llm={"verdict": "pass"})
    decide(store, run_id, "reject", [lead["id"]], "lia@x.com")
    assert store.get_lead(lead["id"])["state"] == "rejected"
    decide(store, run_id, "restore", [lead["id"]], "lia@x.com")
    restored = store.get_lead(lead["id"])
    assert restored["state"] == "needs_review"
    assert restored["prior_state"] == ""


def test_reject_applies_to_qualifying_leads_and_reports_the_rest(store):
    run_id = _run(store)
    a = _lead(store, run_id, email="a@x.com", llm={"verdict": "pass"})
    pushed = _lead(store, run_id, email="p@x.com", state="pushed")
    result = decide(store, run_id, "reject", [a["id"], pushed["id"]], "lia@x.com")
    assert result["updated"] == [a["id"]]
    assert result["refused"][0]["lead_id"] == pushed["id"]
    assert "cannot be rejected" in result["refused"][0]["reason"]


def test_restore_only_applies_to_rejected_or_approved(store):
    run_id = _run(store)
    failed = _lead(store, run_id, email="f@x.com", gates=FAILING, state="qa_failed")
    result = decide(store, run_id, "restore", [failed["id"]], "lia@x.com")
    assert result["updated"] == []
    assert "nothing to restore" in result["refused"][0]["reason"]


def test_a_lead_from_another_run_is_refused(store):
    run_a = _run(store)
    run_b = _run(store)
    lead = _lead(store, run_a, email="a@x.com", llm={"verdict": "pass"})
    result = decide(store, run_b, "reject", [lead["id"]], "lia@x.com")
    assert result["refused"] == [{"lead_id": lead["id"], "reason": "not a lead in this run"}]
    assert store.get_lead(lead["id"])["state"] == "needs_review"


def test_duplicate_ids_in_one_request_are_applied_once(store):
    run_id = _run(store)
    lead = _lead(store, run_id, email="a@x.com", llm={"verdict": "pass"})
    result = decide(store, run_id, "reject", [lead["id"], lead["id"]], "lia@x.com")
    assert result["updated"] == [lead["id"]]


def test_each_decision_is_logged_on_the_run(store):
    run_id = _run(store)
    lead = _lead(store, run_id, email="a@x.com", llm={"verdict": "pass"})
    decide(store, run_id, "reject", [lead["id"]], "lia@x.com")
    assert any("reject 1 lead(s) by lia@x.com" in e["message"] for e in store.list_events(run_id))
