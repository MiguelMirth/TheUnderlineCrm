"""
Shared Gmail OAuth + Monday column helpers for follow-up outreach.

Used by send_followups_sequence.py and triage_gmail_replies.py.
"""
import base64
import json
import os
import re
import html
from datetime import datetime, date
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

from monday_client import MondayClient

from email_outreach import make_email2_body

# Gmail OAuth dependencies:
# pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

current_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(current_dir)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

MONDAY_API_KEY = os.getenv("MONDAY_API_KEY", "").strip()
MASTER_BOARD_ID = int(os.getenv("MASTER_BOARD_ID", "18401545002"))
ACTIVE_OUTREACH_GROUP_ID = os.getenv("ACTIVE_OUTREACH_GROUP_ID", "group_mm0x18c")

# Monday column IDs from your config
COL_LAST_CONTACTED = "date_mm0xerpc"
COL_NEXT_ACTION_DATE = "date_mm0x7ga4"
COL_OUTREACH_STAGE = "color_mm0x44cb"
COL_EMAIL = "email_mm0xb00t"
COL_FIRST_NAME = "text_mm0xjngp"
COL_LAST_NAME = "text_mm0xg7qz"
COL_TITLE = "text_mm0xg2xb"

OUTREACH_STAGE_TARGET = "Email 1 Sent"

# Date range for filter (inclusive) — Email 1 sent between these Last Contacted dates
DEFAULT_DATE_FROM = date(2026, 3, 25)
DEFAULT_DATE_TO = date(2026, 6, 1)

# Brand deck URL for Email 2 (required for live sends)
DECK_LINK = os.getenv("UNDERLINE_DECK_LINK", "").strip()

# Gmail OAuth files
SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", os.path.join("config", "gmail_credentials.json"))
TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", os.path.join("config", "gmail_token.json"))
CANDIDATES_FILE = os.getenv("FOLLOWUP_CANDIDATES_FILE", os.path.join("data", "outputs", "followup_candidates.json"))

if not os.path.isabs(CREDENTIALS_FILE):
    CREDENTIALS_FILE = os.path.join(PROJECT_ROOT, CREDENTIALS_FILE)
if not os.path.isabs(TOKEN_FILE):
    TOKEN_FILE = os.path.join(PROJECT_ROOT, TOKEN_FILE)
if not os.path.isabs(CANDIDATES_FILE):
    CANDIDATES_FILE = os.path.join(PROJECT_ROOT, CANDIDATES_FILE)

# Safety: default dry run so you can verify before sending
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
# 0 means unlimited. Use MAX_SENDS=1 for single live test.
MAX_SENDS = int(os.getenv("MAX_SENDS", "0"))


def parse_date(value: str) -> Optional[date]:
    if not value:
        return None

    value = value.strip()
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y"]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    # Handle text that contains date-like tokens
    m = re.search(r"(\d{4}-\d{2}-\d{2})", value)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            return None

    return None


def in_date_range(d: Optional[date], start: date, end: date) -> bool:
    return d is not None and start <= d <= end


def parse_env_date(name: str, default: date) -> date:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    parsed = parse_date(raw)
    if parsed is None:
        raise ValueError(f"Invalid {name}={raw!r}; use YYYY-MM-DD")
    return parsed


def resolve_date_window(date_from: Optional[date] = None, date_to: Optional[date] = None) -> Tuple[date, date]:
    start = date_from or parse_env_date("FOLLOWUP_DATE_FROM", DEFAULT_DATE_FROM)
    end = date_to or parse_env_date("FOLLOWUP_DATE_TO", DEFAULT_DATE_TO)
    if start > end:
        raise ValueError(f"Date window invalid: {start} is after {end}")
    return start, end


def add_business_days(start: date, business_days: int) -> date:
    current = start
    added = 0
    while added < business_days:
        current = current.fromordinal(current.toordinal() + 1)
        if current.weekday() < 5:
            added += 1
    return current


def column_map(item: Dict[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for cv in item.get("column_values", []):
        col_id = cv.get("id")
        text = cv.get("text") or ""
        if col_id:
            result[col_id] = text.strip()
    return result


def build_gmail_service():
    creds = None

    if not os.path.exists(CREDENTIALS_FILE):
        print("Missing Gmail OAuth client file:", CREDENTIALS_FILE)
        print("Create this file in Google Cloud Console (OAuth client type: Desktop app).")
        print("After adding it, run this script again to authorize Frenchy's mailbox.")
        return None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_header(payload: Dict[str, Any], name: str) -> str:
    headers = payload.get("headers", [])
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def get_default_signature_html(gmail_service) -> str:
    """Fetch the default Gmail signature for the authenticated sender."""
    try:
        profile = gmail_service.users().getProfile(userId="me").execute()
        sender_email = profile.get("emailAddress", "")
        if not sender_email:
            return ""

        send_as = (
            gmail_service.users()
            .settings()
            .sendAs()
            .get(userId="me", sendAsEmail=sender_email)
            .execute()
        )
        return (send_as or {}).get("signature", "") or ""
    except Exception:
        # If signature API is unavailable by policy, fallback to no signature.
        return ""


def find_latest_sent_message_for_recipient(gmail_service, recipient_email: str) -> Optional[Dict[str, Any]]:
    query = f"in:sent to:{recipient_email} newer_than:180d"
    resp = (
        gmail_service.users()
        .messages()
        .list(userId="me", q=query, maxResults=5)
        .execute()
    )

    messages = resp.get("messages", [])
    if not messages:
        return None

    # Pick latest by internalDate
    best = None
    best_ts = -1

    for m in messages:
        full = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=m["id"], format="metadata", metadataHeaders=["Message-ID", "Subject", "To", "Date"])
            .execute()
        )
        ts = int(full.get("internalDate", "0"))
        if ts > best_ts:
            best = full
            best_ts = ts

    return best


def make_followup_body(first_name: str, company_name: str, deck_link: str = "") -> Tuple[str, str]:
    """Email 2 — backward-compatible alias."""
    return make_email2_body(first_name, company_name, deck_link=deck_link)


def fetch_monday_candidates(
    date_from: date,
    date_to: date,
) -> List[Dict[str, Any]]:
    if not MONDAY_API_KEY:
        raise RuntimeError("Missing MONDAY_API_KEY. Set it in your environment or .env file.")

    monday = MondayClient(MONDAY_API_KEY)
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
        if not company_name:
            continue
        if stage != OUTREACH_STAGE_TARGET:
            continue
        if not in_date_range(last_contacted, date_from, date_to):
            continue
        if not email:
            continue

        candidates.append(
            {
                "item_id": item.get("id"),
                "company_name": company_name,
                "first_name": cols.get(COL_FIRST_NAME, ""),
                "last_name": cols.get(COL_LAST_NAME, ""),
                "title": cols.get(COL_TITLE, ""),
                "email": email,
                "last_contacted": str(last_contacted),
                "stage": stage,
            }
        )

    return candidates
