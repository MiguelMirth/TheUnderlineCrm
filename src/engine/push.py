"""
Push approved leads to Monday.

The write needs ENGINE_LIVE_PUSH_ENABLED. The UI asks once before it calls this.
Each created row stores its Monday item id. A later push never creates that row again.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from engine.crm import (
    CrmUnavailable,
    board_id,
    check_board_contract,
    default_monday,
    ensure_snapshot,
    live_push_enabled,
    load_blocklist,
    monday_api_key,
    monday_item_payload,
    new_leads_group_id,
    remember_board_email,
)
from engine.gates import approvable
from engine.models import Preset
from engine.store import Store
from prospecting_qa import normalize_email

PUSHABLE_STATES = frozenset({"approved", "push_failed"})


class PushRefused(Exception):
    """The push cannot start. Nothing was written."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _pushable(lead: dict[str, Any]) -> tuple[bool, str]:
    if lead.get("monday_item_id"):
        return True, ""
    if lead.get("state") not in PUSHABLE_STATES:
        return False, f"lead is {lead.get('state')}, not approved"
    if lead.get("state") == "approved":
        ok, reason = approvable(lead)
        if not ok:
            return False, reason
    return True, ""


def _recheck(store: Store, preset: Preset, monday_factory: Optional[Callable[[], Any]]) -> str:
    """Refresh the snapshot before a write."""
    can_read = monday_factory is not None or bool(monday_api_key())
    if not can_read:
        raise PushRefused("MONDAY_API_KEY is not set, so the board cannot be rechecked.")
    try:
        ensure_snapshot(store, preset, monday_factory=monday_factory, force=True)
    except CrmUnavailable as exc:
        raise PushRefused(str(exc)) from exc
    return "Emails were rechecked against a fresh board read."


def push_leads(
    store: Store,
    preset: Preset,
    run_id: str,
    *,
    actor: str,
    lead_ids: Optional[list[str]] = None,
    monday_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """Push approved leads. Returns {live, rows, message}. Requires the env flag and a valid board contract."""
    run = store.get_run(run_id)
    if run is None:
        raise PushRefused("run not found")
    if run["status"] in {"queued", "running", "enriching", "awaiting_enrich"}:
        raise PushRefused(f"The run is {run['status']}. Wait until it is ready for review.")

    if not live_push_enabled():
        raise PushRefused("ENGINE_LIVE_PUSH_ENABLED is not true.")

    monday = (monday_factory or default_monday)()
    problems = check_board_contract(monday, preset)
    if problems:
        raise PushRefused(" ".join(problems))

    note = _recheck(store, preset, monday_factory)
    try:
        blocklist = load_blocklist(store, preset)
    except CrmUnavailable as exc:
        raise PushRefused(str(exc)) from exc
    seen = set(blocklist.emails)

    if lead_ids:
        chosen = []
        for lead_id in dict.fromkeys(lead_ids):
            lead = store.get_lead(lead_id)
            if lead is None or lead["run_id"] != run_id:
                chosen.append({"id": lead_id, "shelf_brand": "", "email": "", "state": "missing", "monday_item_id": ""})
            else:
                chosen.append(lead)
    else:
        chosen = [lead for lead in store.list_leads(run_id) if lead["state"] in PUSHABLE_STATES]

    rows: list[dict[str, Any]] = []
    created_names: list[str] = []
    board = int(board_id(preset.crm))
    group_id = new_leads_group_id(preset.crm)

    for lead in chosen:
        lead_id = str(lead.get("id") or "")
        brand = lead.get("shelf_brand") or ""
        email = normalize_email(lead.get("email") or "")
        if lead.get("state") == "missing":
            rows.append(_row(lead_id, brand, email, "skipped", reason="not a lead in this run"))
            continue
        if lead.get("monday_item_id"):
            if lead.get("state") != "pushed":
                store.update_lead(lead_id, state="pushed", push_error="")
            rows.append(
                _row(lead_id, brand, email, "already_pushed", monday_item_id=str(lead["monday_item_id"]))
            )
            continue
        ok, reason = _pushable(lead)
        if not ok:
            rows.append(_row(lead_id, brand, email, "skipped", reason=reason))
            continue
        if not email:
            rows.append(_row(lead_id, brand, email, "skipped", reason="no email"))
            continue
        if email in seen:
            reason = f"{email} is already on the board"
            store.update_lead(lead_id, state="push_failed", push_error=reason)
            rows.append(_row(lead_id, brand, email, "failed", reason=reason))
            continue

        item_name, columns = monday_item_payload(lead, preset.crm)
        try:
            res = monday.create_item(board, group_id, item_name, columns, create_labels_if_missing=False)
        except Exception as exc:  # noqa: BLE001 - one row must not abort the rest
            store.update_lead(lead_id, state="push_failed", push_error=str(exc)[:500])
            rows.append(_row(lead_id, item_name, email, "failed", reason=str(exc)))
            continue
        item = ((res or {}).get("data") or {}).get("create_item") or {}
        item_id = str(item.get("id") or "")
        if not item_id:
            err = (res or {}).get("errors") or res or "Monday create failed"
            message = str(err)[:500]
            store.update_lead(lead_id, state="push_failed", push_error=message)
            rows.append(_row(lead_id, item_name, email, "failed", reason=message))
            continue
        store.update_lead(lead_id, state="pushed", monday_item_id=item_id, push_error="")
        remember_board_email(store, preset, email=email, shelf_brand=item_name)
        seen.add(email)
        created_names.append(item_name)
        rows.append(_row(lead_id, item_name, email, "created", monday_item_id=item_id))

    created = sum(1 for row in rows if row["outcome"] == "created")
    if created:
        slack_error = _notify(created, created_names)
        store.add_event(run_id, "info", f"Push of {created} lead(s) by {actor}. {note}")
        if slack_error:
            store.add_event(run_id, "warn", f"Slack notify failed: {slack_error}")
    else:
        store.add_event(run_id, "info", f"Push created nothing. {note}")

    return {"live": True, "rows": rows, "message": f"Created {created} Monday item(s). {note}"}


def _notify(created: int, names: list[str]) -> str:
    try:
        from slack_notify import notify_monday_push

        notify_monday_push(contacts_pushed=created, company_names=names, board_label="New Leads")
    except Exception as exc:  # noqa: BLE001 - the Monday rows already exist
        return str(exc)
    return ""


def _row(
    lead_id: str,
    shelf_brand: str,
    email: str,
    outcome: str,
    *,
    monday_item_id: str = "",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "lead_id": lead_id,
        "shelf_brand": shelf_brand,
        "email": email,
        "outcome": outcome,
        "monday_item_id": monday_item_id,
        "reason": reason,
    }
