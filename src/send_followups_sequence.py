#!/usr/bin/env python3
"""
Unified Gmail follow-up sender for The Underline email sequence.

Thread policy (Lia June 2026):
  Email 2–3 → reply in same thread as Email 1
  Email 4–5 → new thread (fresh subject)

Examples:
  .\\.venv\\Scripts\\python scripts\\send_followups_sequence.py --stage email2
  .\\.venv\\Scripts\\python scripts\\send_followups_sequence.py --stage email3 --live --max-sends 5
  .\\.venv\\Scripts\\python scripts\\send_followups_sequence.py --stage email4 --live
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from email_outreach import (  # noqa: E402
    default_new_thread_subject,
    make_email2_body,
    make_email3_body,
    make_email4_body,
    make_email5_body,
    send_new_thread,
    send_reply_in_thread,
)
from monday_client import MondayClient  # noqa: E402
from send_followups_email1 import (  # noqa: E402
    ACTIVE_OUTREACH_GROUP_ID,
    COL_EMAIL,
    COL_FIRST_NAME,
    COL_LAST_CONTACTED,
    COL_NEXT_ACTION_DATE,
    COL_OUTREACH_STAGE,
    DEFAULT_DATE_FROM,
    DEFAULT_DATE_TO,
    MASTER_BOARD_ID,
    add_business_days,
    build_gmail_service,
    column_map,
    fetch_monday_candidates,
    find_latest_sent_message_for_recipient,
    get_default_signature_html,
    get_header,
    in_date_range,
    parse_date,
    resolve_date_window,
)
from slack_notify import notify_email_batch  # noqa: E402

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_SENDS = int(os.getenv("MAX_SENDS", "0"))
DECK_LINK = os.getenv("UNDERLINE_DECK_LINK", "").strip()


@dataclass(frozen=True)
class StageConfig:
    stage_key: str
    prior_stage: str
    next_stage: str
    in_thread: bool
    needs_deck: bool
    body_fn: Callable[..., Tuple[str, str]]


STAGES: Dict[str, StageConfig] = {
    "email2": StageConfig(
        "email2", "Email 1 Sent", "Email 2 Sent", True, True, make_email2_body
    ),
    "email3": StageConfig(
        "email3", "Email 2 Sent", "Email 3 Sent", True, False, make_email3_body
    ),
    "email4": StageConfig(
        "email4", "Email 3 Sent", "Email 4 Sent", False, False, make_email4_body
    ),
    "email5": StageConfig(
        "email5", "Email 4 Sent", "Email 5 Sent", False, True, make_email5_body
    ),
}


COL_STATE = "text_mm0xrszg"
_FLORIDA = {"fl", "florida", "fla", "miami", "miamidade", "southflorida"}


def in_florida(state: str) -> bool:
    """True when State is blank or a Florida value. A filled other state is out."""
    import re

    compact = re.sub(r"[^a-z]", "", (state or "").lower())
    if not compact:
        return True
    return compact in _FLORIDA


def fetch_candidates_for_stage(
    cfg: StageConfig,
    date_from: date,
    date_to: date,
    *,
    florida_only: bool = True,
) -> List[Dict[str, Any]]:
    if not os.getenv("MONDAY_API_KEY", "").strip():
        raise RuntimeError("Missing MONDAY_API_KEY")

    monday = MondayClient(os.environ["MONDAY_API_KEY"])
    items = monday.get_board_items_with_columns(MASTER_BOARD_ID, limit=500)
    candidates: List[Dict[str, Any]] = []

    for item in items:
        cols = column_map(item)
        group = item.get("group") or {}
        company_name = (item.get("name") or "").strip()
        stage = cols.get(COL_OUTREACH_STAGE, "")
        last_contacted = parse_date(cols.get(COL_LAST_CONTACTED, ""))
        email = cols.get(COL_EMAIL, "")

        if group.get("id") != ACTIVE_OUTREACH_GROUP_ID:
            continue
        if not company_name or stage != cfg.prior_stage:
            continue
        if not in_date_range(last_contacted, date_from, date_to):
            continue
        if not email:
            continue
        state = cols.get(COL_STATE, "")
        if florida_only and not in_florida(state):
            continue

        candidates.append(
            {
                "item_id": item.get("id"),
                "company_name": company_name,
                "first_name": cols.get(COL_FIRST_NAME, ""),
                "email": email,
                "state": state,
                "last_contacted": str(last_contacted),
                "stage": stage,
            }
        )

    return candidates


def run_stage(
    stage_key: str,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    dry_run: Optional[bool] = None,
    max_sends: Optional[int] = None,
    deck_link: str = "",
    florida_only: bool = True,
) -> None:
    cfg = STAGES[stage_key]
    window_from, window_to = resolve_date_window(date_from, date_to)
    effective_dry_run = DRY_RUN if dry_run is None else dry_run
    effective_max_sends = MAX_SENDS if max_sends is None else max_sends
    effective_deck = (deck_link or DECK_LINK).strip()

    print(
        f"Stage {stage_key}: prior={cfg.prior_stage} -> next={cfg.next_stage} | "
        f"thread={'in-thread' if cfg.in_thread else 'NEW'} | "
        f"Last Contacted {window_from} -> {window_to}"
    )
    candidates = fetch_candidates_for_stage(
        cfg, window_from, window_to, florida_only=florida_only
    )
    scope = "Florida or blank State" if florida_only else "any state"
    print(f"Found {len(candidates)} eligible contacts ({scope}).")

    out_path = os.path.join(ROOT, "data", "outputs", f"followup_{stage_key}_candidates.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2)
    print(f"Saved {out_path}")

    if not candidates:
        return

    if not effective_dry_run and cfg.needs_deck and not effective_deck:
        raise RuntimeError("UNDERLINE_DECK_LINK required for live sends with deck (email2/email5).")

    gmail_service = build_gmail_service()
    if gmail_service is None:
        print("Gmail OAuth not configured - stopped before send.")
        return

    monday = MondayClient(os.environ["MONDAY_API_KEY"])
    signature_html = get_default_signature_html(gmail_service)
    sent = skipped = 0
    live_recipients: List[Dict[str, str]] = []

    for c in candidates:
        if not effective_dry_run and effective_max_sends > 0 and sent >= effective_max_sends:
            print(f"Reached MAX_SENDS={effective_max_sends}.")
            break

        recipient = c["email"]
        company = c["company_name"]
        first = c["first_name"]

        if cfg.in_thread:
            try:
                previous = find_latest_sent_message_for_recipient(gmail_service, recipient)
            except Exception as e:
                print(f"SKIP {recipient}: Gmail error ({e})")
                skipped += 1
                continue
            if not previous:
                print(f"SKIP {recipient}: no prior sent thread")
                skipped += 1
                continue
            thread_id = previous.get("threadId", "")
            payload = previous.get("payload", {})
            message_id = get_header(payload, "Message-ID")
            subject = get_header(payload, "Subject") or "Quick follow-up"
        else:
            thread_id = ""
            message_id = ""
            subject = default_new_thread_subject(company, int(stage_key[-1]))

        if cfg.body_fn in (make_email2_body, make_email5_body):
            text_body, html_body = cfg.body_fn(first, company, deck_link=effective_deck)
        else:
            text_body, html_body = cfg.body_fn(first, company)

        if effective_dry_run:
            mode = "in-thread" if cfg.in_thread else "new-thread"
            print(f"DRY RUN [{mode}] -> {recipient} | {subject}")
            sent += 1
            continue

        try:
            if cfg.in_thread:
                send_reply_in_thread(
                    gmail_service, recipient, subject, text_body, html_body,
                    signature_html, thread_id, message_id,
                )
            else:
                send_new_thread(
                    gmail_service, recipient, subject, text_body, html_body, signature_html,
                )

            today = date.today()
            next_action = add_business_days(today, 5)
            monday.update_item_columns(
                MASTER_BOARD_ID,
                c["item_id"],
                {
                    COL_OUTREACH_STAGE: {"label": cfg.next_stage},
                    COL_LAST_CONTACTED: {"date": today.isoformat()},
                    COL_NEXT_ACTION_DATE: {"date": next_action.isoformat()},
                },
            )
            print(f"SENT -> {recipient} ({company})")
            sent += 1
            live_recipients.append(
                {
                    "first_name": first or "",
                    "company_name": company or "",
                    "email": recipient or "",
                }
            )
        except Exception as e:
            print(f"FAILED -> {recipient}: {e}")
            skipped += 1

    print(f"Done. processed={len(candidates)} sent_or_dryrun={sent} skipped={skipped}")

    if not effective_dry_run and live_recipients:
        stage_label = cfg.next_stage  # e.g. "Email 2 Sent"
        notify_email_batch(
            stage_label=stage_label,
            recipients=live_recipients,
            total_sent=len(live_recipients),
        )


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Send Underline sequence follow-ups via Gmail.")
    parser.add_argument(
        "--stage",
        required=True,
        choices=sorted(STAGES.keys()),
        help="email2/email3 = in-thread; email4/email5 = new thread",
    )
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-sends", type=int, default=None)
    parser.add_argument("--deck-link", type=str, default="")
    parser.add_argument(
        "--allow-out-of-state",
        action="store_true",
        help="Include contacts whose State column is not Florida",
    )
    args = parser.parse_args(argv)

    run_stage(
        args.stage,
        date_from=parse_date(args.date_from) if args.date_from else None,
        date_to=parse_date(args.date_to) if args.date_to else None,
        dry_run=False if args.live else None,
        max_sends=args.max_sends,
        deck_link=args.deck_link,
        florida_only=not args.allow_out_of_state,
    )


if __name__ == "__main__":
    main()