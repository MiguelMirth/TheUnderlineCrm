"""
Send Concert Series Email 1 to Monday New Leads (Vertical = Concert Series).

Uses Frenchy's Gmail + mailbox signature. No deck link on touch 1.

Examples:
  .venv\\Scripts\\python scripts\\send_concert_series_email1.py
  .venv\\Scripts\\python scripts\\send_concert_series_email1.py --live --max-sends 5
  .venv\\Scripts\\python scripts\\send_concert_series_email1.py --live --max-sends 50
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from typing import Any, Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from concert_series_config import CONCERT_SERIES_VERTICAL_LABEL  # noqa: E402
from email_outreach import (  # noqa: E402
    concert_series_email1_subject,
    make_concert_series_email1_body,
    send_new_thread,
)
from monday_client import MondayClient  # noqa: E402
from send_followups_email1 import (  # noqa: E402
    ACTIVE_OUTREACH_GROUP_ID,
    COL_EMAIL,
    COL_FIRST_NAME,
    COL_LAST_CONTACTED,
    COL_NEXT_ACTION_DATE,
    COL_OUTREACH_STAGE,
    MASTER_BOARD_ID,
    add_business_days,
    build_gmail_service,
    column_map,
    get_default_signature_html,
)
from slack_notify import notify_email_batch  # noqa: E402

NEW_LEADS_GROUP_ID = os.getenv("NEW_LEADS_GROUP_ID", "group_mm0xbmrj")
COL_VERTICAL = "dropdown_mm0xx10b"
COL_LEAD_STATUS = "status"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_SENDS = int(os.getenv("MAX_SENDS", "0"))


def fetch_concert_series_candidates() -> List[Dict[str, Any]]:
    """New Leads + Vertical Concert Series + Uncontacted + has email."""
    if not os.getenv("MONDAY_API_KEY", "").strip():
        raise RuntimeError("Missing MONDAY_API_KEY")

    monday = MondayClient(os.environ["MONDAY_API_KEY"])
    items = monday.get_board_items_with_columns(MASTER_BOARD_ID, limit=500)
    candidates: List[Dict[str, Any]] = []

    for item in items:
        cols = column_map(item)
        group = item.get("group") or {}
        if group.get("id") != NEW_LEADS_GROUP_ID:
            continue

        vertical = (cols.get(COL_VERTICAL) or "").strip()
        if CONCERT_SERIES_VERTICAL_LABEL.lower() not in vertical.lower():
            continue

        status = (cols.get(COL_LEAD_STATUS) or "").strip()
        if status and status.lower() not in ("uncontacted", ""):
            continue

        stage = (cols.get(COL_OUTREACH_STAGE) or "").strip()
        if stage and "sent" in stage.lower():
            continue

        email = (cols.get(COL_EMAIL) or "").strip()
        company = (item.get("name") or "").strip()
        if not email or not company:
            continue

        candidates.append(
            {
                "item_id": item.get("id"),
                "company_name": company,
                "first_name": cols.get(COL_FIRST_NAME, ""),
                "email": email,
                "vertical": vertical,
                "status": status or "Uncontacted",
                "stage": stage or "(blank)",
            }
        )

    return candidates


def run(
    *,
    dry_run: bool,
    max_sends: int,
    sleep_s: float = 0.4,
) -> None:
    print("--- Concert Series Email 1 ---")
    print(f"  dry_run={dry_run}  max_sends={max_sends or 'unlimited'}")
    print(f"  vertical={CONCERT_SERIES_VERTICAL_LABEL!r}")
    print("  deck=not linked on Email 1 (share-the-deck CTA)")

    candidates = fetch_concert_series_candidates()
    print(f"  Eligible in New Leads: {len(candidates)}")

    out_path = os.path.join(ROOT, "data", "outputs", "concert_series_email1_candidates.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2)
    print(f"  Saved candidates: {out_path}")

    if not candidates:
        return

    gmail_service = build_gmail_service()
    if gmail_service is None:
        print("Gmail OAuth not configured — stopped before send.")
        return

    monday = MondayClient(os.environ["MONDAY_API_KEY"])
    signature_html = get_default_signature_html(gmail_service)
    sent = skipped = 0
    live_recipients: List[Dict[str, str]] = []

    sample = candidates[0]
    sample_subj = concert_series_email1_subject(sample["company_name"])
    sample_text, _ = make_concert_series_email1_body(
        sample["first_name"], sample["company_name"]
    )
    print("\n--- Sample subject ---")
    print(sample_subj)
    print("--- Sample body (text) ---")
    print(sample_text[:700], "...\n" if len(sample_text) > 700 else "\n")

    for c in candidates:
        if max_sends > 0 and sent >= max_sends:
            print(f"Reached MAX_SENDS={max_sends}.", flush=True)
            break

        recipient = c["email"]
        company = c["company_name"]
        first = c["first_name"]
        subject = concert_series_email1_subject(company)
        text_body, html_body = make_concert_series_email1_body(first, company)

        if dry_run:
            print(f"DRY RUN -> {recipient} | {subject}", flush=True)
            sent += 1
            continue

        try:
            send_new_thread(
                gmail_service,
                recipient,
                subject,
                text_body,
                html_body,
                signature_html,
            )
            today = date.today()
            next_action = add_business_days(today, 5)
            monday.update_item_columns(
                MASTER_BOARD_ID,
                c["item_id"],
                {
                    COL_OUTREACH_STAGE: {"label": "Email 1 Sent"},
                    COL_LEAD_STATUS: {"label": "In Sequence"},
                    COL_LAST_CONTACTED: {"date": today.isoformat()},
                    COL_NEXT_ACTION_DATE: {"date": next_action.isoformat()},
                },
            )
            monday.move_item_to_group(c["item_id"], ACTIVE_OUTREACH_GROUP_ID)
            print(f"SENT -> {recipient} ({company})", flush=True)
            sent += 1
            live_recipients.append(
                {
                    "first_name": first or "",
                    "company_name": company or "",
                    "email": recipient or "",
                }
            )
            if sleep_s > 0:
                time.sleep(sleep_s)
        except Exception as e:  # noqa: BLE001
            print(f"FAILED -> {recipient}: {e}", flush=True)
            skipped += 1

    print(f"\nDone. sent_or_dryrun={sent} skipped={skipped}", flush=True)
    if not dry_run and live_recipients:
        notify_email_batch(
            stage_label="Concert Series Email 1 Sent",
            recipients=live_recipients,
            total_sent=len(live_recipients),
        )


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(description="Send Concert Series Email 1 via Gmail")
    p.add_argument("--live", action="store_true", help="Actually send (default is dry-run)")
    p.add_argument("--max-sends", type=int, default=None, help="Cap live sends (0 = unlimited)")
    p.add_argument("--sleep", type=float, default=0.4, help="Seconds between live sends")
    args = p.parse_args(argv)

    dry_run = not args.live
    max_sends = MAX_SENDS if args.max_sends is None else args.max_sends
    run(dry_run=dry_run, max_sends=max_sends, sleep_s=args.sleep)


if __name__ == "__main__":
    main()
