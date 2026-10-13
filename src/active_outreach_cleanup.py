"""
Audit and clean outreach contact rows on the Monday master board.

Uses the same QA gates as prospecting (email, title, org name) plus structural checks
(missing contact fields, duplicate emails within each group).

Default group: Active Outreach (see scripts/cleanup_active_outreach.py).
Concert Series contacts are identified by the Vertical column, not a board group.
"""
from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from monday_client import MondayClient
from prospecting_qa import (
    email_blocked,
    normalize_email,
    org_name_blocked,
    parse_email_column_value,
    title_gate,
)

_ROOT = Path(__file__).resolve().parent.parent

COL_EMAIL = "email_mm0xb00t"
COL_FIRST_NAME = "text_mm0xjngp"
COL_LAST_NAME = "text_mm0xg7qz"
COL_TITLE = "text_mm0xg2xb"
COL_OUTREACH_STAGE = "color_mm0x44cb"
COL_LEAD_STATUS = "status"

OUTREACH_STAGE_RANK = {
    "levit bloc music": 110,
    "levitt bloc music": 110,
    "email 5 sent": 50,
    "email 4 sent": 45,
    "email 3 sent": 40,
    "email 2 sent": 35,
    "email 1 sent": 30,
    "completed (no reply)": 20,
    "": 0,
}


def item_to_row(item: dict[str, Any]) -> dict[str, str]:
    """Flatten Monday item + column_values to a simple dict."""
    cols: dict[str, Any] = {cv.get("id"): cv for cv in item.get("column_values") or []}
    email_cv = cols.get(COL_EMAIL) or {}
    group = item.get("group") or {}
    return {
        "item_id": str(item.get("id") or ""),
        "company_name": (item.get("name") or "").strip(),
        "group_id": (group.get("id") or "").strip(),
        "group_title": (group.get("title") or "").strip(),
        "first_name": (cols.get(COL_FIRST_NAME) or {}).get("text") or "",
        "last_name": (cols.get(COL_LAST_NAME) or {}).get("text") or "",
        "title": (cols.get(COL_TITLE) or {}).get("text") or "",
        "email": parse_email_column_value(email_cv),
        "outreach_stage": (cols.get(COL_OUTREACH_STAGE) or {}).get("text") or "",
        "lead_status": (cols.get(COL_LEAD_STATUS) or {}).get("text") or "",
    }


def _outreach_rank(stage: str) -> int:
    return OUTREACH_STAGE_RANK.get((stage or "").strip().lower(), 10)


def _load_company_blocklist() -> set[str]:
    """Human-edited blacklist.txt. The engine does not rewrite this file."""
    from engine.crm import read_blacklist

    return read_blacklist(_ROOT / "data" / "inputs" / "blacklist.txt")


def classify_active_outreach_row(
    row: dict[str, str],
    *,
    company_blocklist: set[str] | None = None,
) -> tuple[str, list[str]]:
    """
    Return (verdict, reasons) where verdict is 'keep' or 'delete'.
    """
    reasons: list[str] = []
    company = (row.get("company_name") or "").strip()
    title = (row.get("title") or "").strip()
    email_raw = (row.get("email") or "").strip()
    email_n = normalize_email(email_raw)
    first = (row.get("first_name") or "").strip()
    last = (row.get("last_name") or "").strip()

    blocklist = company_blocklist if company_blocklist is not None else _load_company_blocklist()
    if company.lower() in blocklist:
        reasons.append("blocklisted_company")

    org_bad = org_name_blocked(company)
    if org_bad:
        reasons.append(f"bad_org:{org_bad}")

    if not email_n:
        reasons.append("missing_email")
    elif "@" not in email_n:
        reasons.append("invalid_email")
    else:
        em_bad = email_blocked(email_n)
        if em_bad:
            reasons.append(f"blocked_email:{em_bad}")

    if not title:
        reasons.append("empty_title")
    else:
        ok_title, tr = title_gate(title)
        if not ok_title:
            reasons.append(f"bad_title:{tr}")

    # Company-only pulse: brand as item name with no real contact person
    if not first and not last and not email_n:
        reasons.append("company_pulse_no_contact")

    if reasons:
        return "delete", reasons
    return "keep", []


def _pick_keeper(rows: list[dict[str, str]]) -> dict[str, str]:
    """Among duplicate-email rows, keep highest outreach stage then highest item id."""
    return max(
        rows,
        key=lambda r: (_outreach_rank(r.get("outreach_stage") or ""), int(r.get("item_id") or 0)),
    )


def default_cleanup_group_ids() -> list[str]:
    """Active Outreach. Concert Series is the Vertical column, not a board group."""
    active = os.getenv("ACTIVE_OUTREACH_GROUP_ID", "group_mm0x18c").strip()
    return [active] if active else []


def _audit_group_rows(
    rows: list[dict[str, str]],
    *,
    company_blocklist: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    """Classify rows and mark within-group duplicate emails for deletion."""
    classified: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()

    for row in rows:
        verdict, reasons = classify_active_outreach_row(row, company_blocklist=company_blocklist)
        classified.append({**row, "verdict": verdict, "reasons": reasons})
        for r in reasons:
            reason_counts[r.split(":", 1)[0]] += 1

    by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in classified:
        em = normalize_email(row.get("email") or "")
        if em:
            by_email[em].append(row)

    dup_count = 0
    for group_rows in by_email.values():
        if len(group_rows) < 2:
            continue
        keeper = _pick_keeper(group_rows)
        for row in group_rows:
            if row["item_id"] == keeper["item_id"]:
                continue
            row["verdict"] = "delete"
            if "duplicate_email_in_group" not in row["reasons"]:
                row["reasons"].append("duplicate_email_in_group")
            dup_count += 1

    reason_counts["duplicate_email_in_group"] += dup_count
    proposed = [r for r in classified if r["verdict"] == "delete"]
    keepers = [r for r in classified if r["verdict"] == "keep"]
    return proposed, keepers, reason_counts


def audit_active_outreach(
    monday: MondayClient,
    board_id: int,
    group_id: str,
) -> dict[str, Any]:
    """Audit a single group (backward compatible)."""
    return audit_outreach_groups(monday, board_id, [group_id])


def audit_outreach_groups(
    monday: MondayClient,
    board_id: int,
    group_ids: list[str],
) -> dict[str, Any]:
    """Fetch items in one or more groups and propose deletions."""
    target_ids = set(group_ids)
    items = monday.get_board_items_with_columns(board_id)
    scoped = [i for i in items if (i.get("group") or {}).get("id") in target_ids]
    rows = [item_to_row(i) for i in scoped]

    blocklist = _load_company_blocklist()
    by_group: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_group[row.get("group_id") or ""].append(row)

    all_proposed: list[dict[str, Any]] = []
    all_keepers: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    per_group: list[dict[str, Any]] = []

    for gid in group_ids:
        group_rows = by_group.get(gid) or []
        proposed, keepers, counts = _audit_group_rows(group_rows, company_blocklist=blocklist)
        reason_counts.update(counts)
        all_proposed.extend(proposed)
        all_keepers.extend(keepers)
        title = (group_rows[0].get("group_title") if group_rows else "") or gid
        per_group.append(
            {
                "group_id": gid,
                "group_title": title,
                "total": len(group_rows),
                "proposed_deletions": len(proposed),
                "keepers": len(keepers),
            }
        )

    meta = monday.get_board_metadata(board_id) or {}
    slug = monday.get_account_slug()
    board_url = f"https://{slug}.monday.com/boards/{board_id}" if slug else ""

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "board_id": board_id,
        "board_name": meta.get("name") or "",
        "board_url": board_url,
        "group_ids": group_ids,
        "groups": per_group,
        "group_id": group_ids[0] if len(group_ids) == 1 else None,
        "summary": {
            "total_rows": len(rows),
            "total_active_outreach": len(rows),  # legacy key
            "proposed_deletions": len(all_proposed),
            "keepers": len(all_keepers),
            "reason_counts": dict(reason_counts),
            "per_group": per_group,
        },
        "proposed_deletions": [
            {
                "action": "delete_item",
                "item_id": r["item_id"],
                "group_id": r.get("group_id") or "",
                "group_title": r.get("group_title") or "",
                "company_name": r["company_name"],
                "email": r.get("email") or "",
                "title": r.get("title") or "",
                "first_name": r.get("first_name") or "",
                "last_name": r.get("last_name") or "",
                "outreach_stage": r.get("outreach_stage") or "",
                "lead_status": r.get("lead_status") or "",
                "reasons": r.get("reasons") or [],
            }
            for r in all_proposed
        ],
        "keepers_sample": all_keepers[:25],
    }


def write_hitl_bundle(report: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    label = "outreach_cleanup"
    json_path = out_dir / f"HITL_{label}_{ts}.json"
    csv_path = out_dir / f"HITL_{label}_{ts}.csv"
    md_path = out_dir / f"HITL_{label}_{ts}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    fieldnames = [
        "item_id",
        "group_title",
        "company_name",
        "email",
        "title",
        "outreach_stage",
        "lead_status",
        "reasons",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in report.get("proposed_deletions") or []:
            w.writerow(
                {
                    **{k: row.get(k, "") for k in fieldnames if k != "reasons"},
                    "reasons": "; ".join(row.get("reasons") or []),
                }
            )

    summary = report.get("summary") or {}
    group_lines = summary.get("per_group") or report.get("groups") or []
    lines = [
        f"# Outreach cleanup HITL — {ts}",
        "",
        f"Board: {report.get('board_name')} ({report.get('board_url')})",
        "",
        "## Summary",
        f"- Total rows (all groups): **{summary.get('total_rows', summary.get('total_active_outreach', 0))}**",
        f"- Proposed deletions: **{summary.get('proposed_deletions', 0)}**",
        f"- Keepers: **{summary.get('keepers', 0)}**",
        "",
        "### Per group",
    ]
    for g in group_lines:
        lines.append(
            f"- **{g.get('group_title') or g.get('group_id')}**: "
            f"{g.get('total', 0)} total, {g.get('proposed_deletions', 0)} delete, {g.get('keepers', 0)} keep"
        )
    lines.extend(["", "### Reasons"])
    for reason, count in sorted((summary.get("reason_counts") or {}).items(), key=lambda x: -x[1]):
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "## Proposed deletions (review before --apply)", ""])
    for row in (report.get("proposed_deletions") or [])[:200]:
        reasons = ", ".join(row.get("reasons") or [])
        lines.append(
            f"- `{row.get('item_id')}` | {row.get('group_title')} | {row.get('company_name')} | "
            f"{row.get('email')} | {row.get('title')} | {row.get('outreach_stage')} | {reasons}"
        )
    if len(report.get("proposed_deletions") or []) > 200:
        lines.append(f"- … and {len(report['proposed_deletions']) - 200} more (see CSV)")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "md": str(md_path)}


def apply_cleanup(
    monday: MondayClient,
    report: dict[str, Any],
    *,
    move_to_group: str | None = None,
    max_deletes: int = 0,
) -> dict[str, Any]:
    """Delete (or move) proposed rows. Returns execution stats."""
    ids = [r["item_id"] for r in report.get("proposed_deletions") or []]
    if max_deletes > 0:
        ids = ids[:max_deletes]

    deleted = 0
    moved = 0
    errors: list[dict[str, str]] = []

    for item_id in ids:
        if move_to_group:
            res = monday.move_item_to_group(item_id, move_to_group)
            ok = bool(res and res.get("data") and res["data"].get("move_item_to_group"))
            if ok:
                moved += 1
            else:
                errors.append({"item_id": item_id, "error": str(res)[:200]})
        else:
            res = monday.delete_item(item_id)
            ok = bool(res and res.get("data") and res["data"].get("delete_item"))
            if ok:
                deleted += 1
            else:
                errors.append({"item_id": item_id, "error": str(res)[:200]})

    return {"deleted": deleted, "moved": moved, "errors": errors, "attempted": len(ids)}
