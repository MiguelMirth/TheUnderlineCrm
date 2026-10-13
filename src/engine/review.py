"""
Operator decisions on leads: reject, restore, approve.

Approve is all-or-nothing. If any selected lead is not approvable (gates.approvable), nothing is written and
the refused list comes back, so the UI can show each reason. Reject and restore apply to the leads that
qualify and report the rest.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from engine.gates import approvable
from engine.store import Store

REJECTABLE_STATES = frozenset(
    {
        "candidate",
        "blocked",
        "qa_failed",
        "llm_failed",
        "shortlisted",
        "post_qa_failed",
        "needs_review",
        "approved",
        "push_failed",
    }
)
RESTORABLE_STATES = frozenset({"rejected", "approved"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decide(store: Store, run_id: str, action: str, lead_ids: list[str], actor: str) -> dict[str, Any]:
    """Apply one decision to the given leads. Returns {updated: [...], refused: [{lead_id, reason}]}."""
    updated: list[str] = []
    refused: list[dict[str, str]] = []
    leads: dict[str, dict[str, Any]] = {}
    for lead_id in dict.fromkeys(lead_ids):  # de-duplicate, keep order
        lead = store.get_lead(lead_id)
        if lead is None or lead["run_id"] != run_id:
            refused.append({"lead_id": lead_id, "reason": "not a lead in this run"})
            continue
        leads[lead_id] = lead

    if action == "approve":
        for lead_id, lead in leads.items():
            ok, reason = approvable(lead)
            if not ok:
                refused.append({"lead_id": lead_id, "reason": reason})
        if refused:
            return {"updated": [], "refused": refused}
        for lead_id, lead in leads.items():
            if lead["state"] == "approved":
                updated.append(lead_id)
                continue
            store.update_lead(
                lead_id,
                prior_state=lead["state"],
                state="approved",
                decided_by=actor,
                decided_at=_now(),
            )
            updated.append(lead_id)

    elif action == "reject":
        for lead_id, lead in leads.items():
            if lead["state"] == "rejected":
                updated.append(lead_id)
                continue
            if lead["state"] not in REJECTABLE_STATES:
                refused.append({"lead_id": lead_id, "reason": f"a {lead['state']} lead cannot be rejected"})
                continue
            store.update_lead(
                lead_id,
                prior_state=lead["state"],
                state="rejected",
                decided_by=actor,
                decided_at=_now(),
            )
            updated.append(lead_id)

    elif action == "restore":
        for lead_id, lead in leads.items():
            if lead["state"] not in RESTORABLE_STATES:
                refused.append({"lead_id": lead_id, "reason": f"a {lead['state']} lead has nothing to restore"})
                continue
            target = lead["prior_state"] or "needs_review"
            store.update_lead(
                lead_id,
                state=target,
                prior_state="",
                decided_by=actor,
                decided_at=_now(),
            )
            updated.append(lead_id)

    else:
        raise ValueError(f"unknown action {action!r}")

    if updated:
        store.add_event(run_id, "info", f"{action} {len(updated)} lead(s) by {actor}")
    return {"updated": updated, "refused": refused}
