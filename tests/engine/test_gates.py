"""approvable(): the one rule the approve endpoint and the push builder share. The LLM can never make a fail pass."""
from __future__ import annotations

from engine.gates import approvable

_PASSING = [{"stage": 1, "gate_id": "title_gate", "passed": True, "reason": ""}]


def _lead(**overrides):
    lead = {
        "state": "needs_review",
        "gates": list(_PASSING),
        "llm": {"verdict": "pass"},
        "person": {"enriched": True},
    }
    lead.update(overrides)
    return lead


def test_clean_lead_is_approvable():
    assert approvable(_lead()) == (True, "ok")


def test_a_failed_deterministic_gate_blocks_approval():
    gates = _PASSING + [{"stage": 6, "gate_id": "email_blocked", "passed": False, "reason": "domain .gov"}]
    ok, reason = approvable(_lead(gates=gates))
    assert ok is False
    assert reason == "email_blocked: domain .gov"


def test_llm_flag_stays_approvable_and_llm_fail_does_not():
    assert approvable(_lead(llm={"verdict": "flag"}))[0] is True
    ok, reason = approvable(_lead(llm={"verdict": "fail"}))
    assert ok is False
    assert "LLM verdict fail" in reason


def test_missing_llm_is_not_approvable():
    ok, reason = approvable(_lead(llm=None))
    assert ok is False
    assert reason == "LLM QA missing"


def test_unenriched_contact_is_not_approvable():
    ok, reason = approvable(_lead(person={"enriched": False}))
    assert ok is False
    assert reason == "contact not enriched"


def test_rejected_and_shortlisted_leads_are_not_approvable():
    assert approvable(_lead(state="rejected"))[0] is False
    assert approvable(_lead(state="shortlisted"))[0] is False


def test_pushed_lead_is_not_approvable_again():
    ok, reason = approvable(_lead(state="pushed"))
    assert ok is False
    assert reason == "already pushed"
