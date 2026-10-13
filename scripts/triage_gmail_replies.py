#!/usr/bin/env python3
"""
Triage inbound Gmail messages (REPLIES label) for a calendar month using Gemini,
match to Monday Master Outreach, and optionally apply CRM updates.

Examples:
  .\\.venv\\Scripts\\python scripts\\triage_gmail_replies.py --month 2026-05
  .\\.venv\\Scripts\\python scripts\\triage_gmail_replies.py --month 2025-12 --max 20
  .\\.venv\\Scripts\\python scripts\\triage_gmail_replies.py --month 2026-05 --apply

Requires: GEMINI_API_KEY, MONDAY_API_KEY, Gmail OAuth under config/ (Frenchy mailbox).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from gmail_replies import (  # noqa: E402
    fetch_inbound_replies_for_month,
    filter_skip_senders,
    month_date_range,
    parse_skip_senders,
)
from monday_client import MondayClient  # noqa: E402
from reply_triage_gemini import classify_reply  # noqa: E402
from reply_triage_monday import (  # noqa: E402
    COL_LEAD_STATUS,
    COL_OUTREACH_STAGE,
    COL_TITLE,
    MASTER_BOARD_ID,
    apply_triage_update,
    build_email_index,
    column_text,
    group_id_for_hint,
    load_triage_index,
    monday_context_for_email,
    triage_to_column_values,
)


from send_followups_email1 import build_gmail_service  # noqa: E402
from reply_triage_gemini import _sanitize_error  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)

DEFAULT_OUTPUT_DIR = os.path.join(ROOT, "data", "outputs")
MONDAY_INDEX_CACHE = os.path.join(DEFAULT_OUTPUT_DIR, "monday_triage_index_cache.json")


def parse_month_arg(value: str) -> tuple[int, int]:
    """Accept YYYY-MM or YYYY-M."""
    value = value.strip()
    if "-" not in value:
        raise argparse.ArgumentTypeError("Use YYYY-MM, e.g. 2026-05")
    y, m = value.split("-", 1)
    year, month = int(y), int(m)
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError("month must be 01-12")
    return year, month


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")


def write_hitl_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_review_md(path: str, rows: List[Dict[str, Any]], year: int, month: int) -> None:
    start, end = month_date_range(year, month)
    lines = [
        f"# Gmail REPLIES triage — {year}-{month:02d}",
        f"",
        f"Window: {start.isoformat()} through {(end.isoformat())} (exclusive end)",
        f"Rows: {len(rows)}",
        f"",
        "| Apply? | Confidence | Reply type | From | Monday company | Lead status | Group |",
        "|--------|------------|------------|------|----------------|-------------|-------|",
    ]
    for r in rows:
        tri = r.get("triage") or {}
        lines.append(
            "| {apply} | {conf} | {rt} | {frm} | {co} | {ls} | {gr} |".format(
                apply="yes" if tri.get("apply_to_monday") and r.get("monday_item_id") else "no",
                conf=tri.get("confidence", ""),
                rt=tri.get("reply_type", ""),
                frm=(r.get("from_email") or "")[:40],
                co=(r.get("monday_company") or "")[:30],
                ls=tri.get("lead_status", ""),
                gr=tri.get("suggested_group", ""),
            )
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage Gmail REPLIES label by month with Gemini.")
    parser.add_argument(
        "--month",
        type=parse_month_arg,
        required=True,
        help="Calendar month to review (YYYY-MM), e.g. 2026-05 or 2025-12",
    )
    parser.add_argument("--max", type=int, default=0, help="Max messages to process (0 = all in month)")
    parser.add_argument(
        "--label",
        default=os.getenv("GMAIL_REPLIES_LABEL", "REPLIES"),
        help="Gmail label name (default REPLIES)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates to Monday (default: dry-run JSON/CSV only)",
    )
    parser.add_argument(
        "--gemini-model",
        default=os.getenv("GEMINI_TRIAGE_MODEL", "gemini-2.5-flash-lite"),
    )
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds between Gemini calls")
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Fetch Gmail + Monday match only; skip Gemini (fast sanity check)",
    )
    parser.add_argument(
        "--refresh-monday-cache",
        action="store_true",
        help="Re-download Monday email index and save cache (otherwise reuse cache if present)",
    )
    args = parser.parse_args()

    year, month = args.month
    max_messages = args.max if args.max > 0 else 500

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    monday_key = os.getenv("MONDAY_API_KEY", "").strip()
    if not gemini_key:
        print("Missing GEMINI_API_KEY in .env")
        return 1
    if not monday_key:
        print("Missing MONDAY_API_KEY in .env")
        return 1

    log("Connecting Gmail (Frenchy OAuth)...")
    gmail = build_gmail_service()
    if gmail is None:
        log("Gmail OAuth not configured. Add config/gmail_credentials.json and authorize.")
        log("If a browser window opened, complete sign-in locally then re-run.")
        return 1

    log(f"Fetching inbound label:{args.label} for {year}-{month:02d} (max {max_messages})...")
    messages = fetch_inbound_replies_for_month(
        gmail,
        year,
        month,
        label=args.label,
        max_messages=max_messages,
        snippet_only=args.fetch_only,
    )
    skip_senders = parse_skip_senders()
    messages, n_skip = filter_skip_senders(messages, skip_senders)
    if n_skip:
        log(f"Skipped {n_skip} message(s) from internal senders: {', '.join(sorted(skip_senders))}")
    log(f"Processing {len(messages)} inbound message(s) after sender filter.")
    if not messages:
        log("Nothing to triage for this month/label. Check label name or try another --month.")
        return 0

    monday = MondayClient(monday_key)
    items: List[Dict[str, Any]]
    if (
        os.path.isfile(MONDAY_INDEX_CACHE)
        and not args.refresh_monday_cache
    ):
        log(f"Loading Monday index from cache ({MONDAY_INDEX_CACHE})...")
        with open(MONDAY_INDEX_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
        items = cache.get("items") or []
        log(f"  {len(items)} items (cached at {cache.get('cached_at', '?')})")
    else:
        log("Loading Monday email index (paginated, minimal columns)...")

        def on_page(n: int, batch: int) -> None:
            log(f"  Monday page {n}: +{batch} items")

        items = load_triage_index(monday, MASTER_BOARD_ID, on_page=on_page)
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        with open(MONDAY_INDEX_CACHE, "w", encoding="utf-8") as f:
            json.dump({"cached_at": stamp(), "items": items}, f)
        log(f"  Saved Monday cache ({len(items)} items).")

    email_index = build_email_index(items)
    log(f"Ready: {len(items)} Monday items indexed for email matching.")

    results: List[Dict[str, Any]] = []
    applied = 0
    skipped_apply = 0
    errors = 0

    for i, msg in enumerate(messages, 1):
        item, match_kind = monday_context_for_email(email_index, msg.from_email)
        monday_company = (item.get("name") or "").strip() if item else ""
        monday_id = str(item.get("id") or "") if item else ""
        row: Dict[str, Any] = {
            "gmail_message_id": msg.gmail_message_id,
            "thread_id": msg.thread_id,
            "from_email": msg.from_email,
            "from_name": msg.from_name,
            "subject": msg.subject,
            "received_at": msg.received_at,
            "snippet": msg.snippet[:300],
            "monday_item_id": monday_id,
            "monday_company": monday_company,
            "monday_match": match_kind,
        }

        if args.fetch_only:
            triage = {
                "reply_type": "pending",
                "lead_status": None,
                "interest_level": None,
                "suggested_group": "none",
                "next_action": "",
                "next_action_date": None,
                "notes_summary": "",
                "apply_to_monday": False,
                "confidence": "low",
            }
        else:
            log(f"  [{i}/{len(messages)}] Gemini: {msg.from_email[:40]} ...")
            try:
                triage = classify_reply(
                    api_key=gemini_key,
                    model=args.gemini_model,
                    from_email=msg.from_email,
                    from_name=msg.from_name,
                    subject=msg.subject,
                    received_at=msg.received_at,
                    body_text=msg.body_text,
                    snippet=msg.snippet,
                    monday_company=monday_company,
                    monday_lead_status=column_text(item, COL_LEAD_STATUS) if item else "",
                    monday_outreach_stage=column_text(item, COL_OUTREACH_STAGE) if item else "",
                    monday_title=column_text(item, COL_TITLE) if item else "",
                )
            except Exception as e:
                triage = {
                    "reply_type": "ambiguous",
                    "lead_status": "Replied",
                    "interest_level": None,
                    "suggested_group": "none",
                    "next_action": "",
                    "next_action_date": None,
                    "notes_summary": f"Triage error: {_sanitize_error(e)}",
                    "apply_to_monday": False,
                    "confidence": "low",
                }
                row["triage_error"] = _sanitize_error(e)

        row["triage"] = triage
        results.append(row)

        should_apply = (
            args.apply
            and triage.get("apply_to_monday")
            and monday_id
            and triage.get("confidence") != "low"
        )
        if args.apply and triage.get("apply_to_monday") and monday_id and not should_apply:
            skipped_apply += 1

        if should_apply:
            cols = triage_to_column_values(
                triage,
                received_at=msg.received_at,
                reply_type=triage.get("reply_type", ""),
            )
            gid = group_id_for_hint(triage.get("suggested_group", "none"))
            ok, detail = apply_triage_update(
                monday,
                board_id=MASTER_BOARD_ID,
                item_id=monday_id,
                column_values=cols,
                group_id=gid,
            )
            row["monday_apply"] = ok
            row["monday_apply_detail"] = detail
            if ok:
                applied += 1
            else:
                errors += 1
        else:
            row["monday_apply"] = False
            row["monday_apply_detail"] = "dry_run" if not args.apply else "skipped"

        if args.sleep > 0 and not args.fetch_only and i < len(messages):
            time.sleep(args.sleep)

    tag = f"{year}-{month:02d}"
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(DEFAULT_OUTPUT_DIR, f"reply_triage_{tag}.json")
    csv_path = os.path.join(DEFAULT_OUTPUT_DIR, f"reply_triage_{tag}_HITL.csv")
    md_path = os.path.join(DEFAULT_OUTPUT_DIR, f"reply_triage_{tag}_review.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": stamp(),
                "year": year,
                "month": month,
                "label": args.label,
                "dry_run": not args.apply,
                "message_count": len(results),
                "rows": results,
            },
            f,
            indent=2,
        )

    flat_rows: List[Dict[str, Any]] = []
    for r in results:
        tri = r.get("triage") or {}
        flat_rows.append(
            {
                "from_email": r.get("from_email"),
                "from_name": r.get("from_name"),
                "received_at": r.get("received_at"),
                "subject": r.get("subject"),
                "monday_item_id": r.get("monday_item_id"),
                "monday_company": r.get("monday_company"),
                "monday_match": r.get("monday_match"),
                "reply_type": tri.get("reply_type"),
                "lead_status": tri.get("lead_status"),
                "interest_level": tri.get("interest_level"),
                "suggested_group": tri.get("suggested_group"),
                "apply_to_monday": tri.get("apply_to_monday"),
                "confidence": tri.get("confidence"),
                "next_action": tri.get("next_action"),
                "next_action_date": tri.get("next_action_date"),
                "notes_summary": tri.get("notes_summary"),
                "monday_apply": r.get("monday_apply"),
                "gmail_message_id": r.get("gmail_message_id"),
            }
        )
    write_hitl_csv(csv_path, flat_rows)
    write_review_md(md_path, results, year, month)

    unmatched = sum(1 for r in results if not r.get("monday_item_id"))
    warm = sum(1 for r in results if (r.get("triage") or {}).get("reply_type") == "positive_curious")

    log("")
    log(f"Wrote {json_path}")
    log(f"Wrote {csv_path}")
    log(f"Wrote {md_path}")
    log(f"Summary: {len(results)} messages | {unmatched} no Monday match | {warm} positive/curious")
    if args.fetch_only:
        log("Fetch-only run (no Gemini). Re-run without --fetch-only to classify.")
    elif args.apply:
        log(f"Monday updates applied: {applied} | skipped: {skipped_apply} | errors: {errors}")
    else:
        log("Dry run. Review CSV/JSON, then re-run with --apply to update Monday.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
