"""
Fetch inbound messages from Frenchy's Gmail with the REPLIES label, scoped by calendar month.
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

from send_followups_email1 import build_gmail_service, get_header

# Gmail MIME trees can be extremely deep; cap traversal to avoid RecursionError.
MAX_MIME_DEPTH = 64

# Internal / agency inboxes to ignore in REPLIES triage (comma-separated in TRIAGE_SKIP_SENDERS).
DEFAULT_SKIP_SENDERS = frozenset({"lia@knowyourmirth.com"})


@dataclass
class InboundReplyMessage:
    gmail_message_id: str
    thread_id: str
    from_email: str
    from_name: str
    subject: str
    received_at: str  # ISO date
    snippet: str
    body_text: str


def month_date_range(year: int, month: int) -> Tuple[date, date]:
    """Inclusive start, exclusive end (first day of next month)."""
    if month < 1 or month > 12:
        raise ValueError("month must be 1-12")
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def gmail_query_for_month(
    year: int,
    month: int,
    *,
    label: str = "REPLIES",
) -> str:
    """Gmail search: label + month window + exclude messages we sent."""
    start, end = month_date_range(year, month)
    after = start.strftime("%Y/%m/%d")
    before = end.strftime("%Y/%m/%d")
    return f'label:{label} after:{after} before:{before} -from:me'


def parse_from_header(value: str) -> Tuple[str, str]:
    name, addr = parseaddr(value or "")
    return (name or "").strip(), (addr or "").strip().lower()


def parse_skip_senders(env_value: str | None = None) -> frozenset[str]:
    """Normalized sender emails to exclude from triage."""
    raw = env_value if env_value is not None else os.getenv("TRIAGE_SKIP_SENDERS", "")
    emails = {e.strip().lower() for e in DEFAULT_SKIP_SENDERS}
    if raw.strip():
        for part in raw.split(","):
            p = part.strip().lower()
            if p:
                emails.add(p)
    return frozenset(emails)


def filter_skip_senders(
    messages: List[InboundReplyMessage],
    skip: frozenset[str],
) -> tuple[List[InboundReplyMessage], int]:
    if not skip:
        return messages, 0
    kept: List[InboundReplyMessage] = []
    skipped = 0
    for m in messages:
        if m.from_email in skip:
            skipped += 1
            continue
        kept.append(m)
    return kept, skipped


def _decode_part_data(data: str) -> str:
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data + "==")
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def iter_mime_parts(root: Dict[str, Any], *, max_depth: int = MAX_MIME_DEPTH) -> List[Dict[str, Any]]:
    """Iterative MIME walk (avoids recursion on pathological nested multipart messages)."""
    if not root:
        return []
    out: List[Dict[str, Any]] = []
    stack: List[Tuple[Dict[str, Any], int]] = [(root, 0)]
    while stack:
        part, depth = stack.pop()
        if not isinstance(part, dict):
            continue
        out.append(part)
        if depth >= max_depth:
            continue
        children = part.get("parts") or []
        for child in reversed(children):
            if isinstance(child, dict):
                stack.append((child, depth + 1))
    return out


def extract_plain_body(payload: Dict[str, Any], *, max_chars: int = 12000) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    plain_chunks: List[str] = []
    html_chunks: List[str] = []

    for part in iter_mime_parts(payload):
        mime = (part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data")
        if not data:
            continue
        decoded = _decode_part_data(data)
        if not decoded:
            continue
        if mime == "text/plain":
            plain_chunks.append(decoded)
        elif mime == "text/html":
            html_chunks.append(decoded)

    text = "\n".join(c for c in plain_chunks if c).strip()
    if not text and html_chunks:
        raw = "\n".join(html_chunks)
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text


def _message_internal_date_iso(msg: Dict[str, Any]) -> str:
    ms = msg.get("internalDate")
    if ms:
        try:
            dt = datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
            return dt.date().isoformat()
        except (TypeError, ValueError):
            pass
    date_hdr = get_header(msg.get("payload") or {}, "Date")
    if date_hdr:
        try:
            dt = parsedate_to_datetime(date_hdr)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.date().isoformat()
        except (TypeError, ValueError):
            pass
    return ""


def fetch_inbound_replies_for_month(
    gmail_service,
    year: int,
    month: int,
    *,
    label: str = "REPLIES",
    max_messages: int = 500,
    mailbox_email: Optional[str] = None,
    snippet_only: bool = False,
) -> List[InboundReplyMessage]:
    """
    List messages matching label + month; keep only inbound (From != authenticated mailbox).

    If snippet_only=True, uses Gmail metadata format (faster; body_text falls back to snippet).
    """
    if not mailbox_email:
        profile = gmail_service.users().getProfile(userId="me").execute()
        mailbox_email = (profile.get("emailAddress") or "").strip().lower()

    query = gmail_query_for_month(year, month, label=label)
    results: List[InboundReplyMessage] = []
    page_token: Optional[str] = None
    msg_format = "metadata" if snippet_only else "full"
    metadata_headers = ["From", "Subject", "Date"] if snippet_only else None

    while len(results) < max_messages:
        batch = min(100, max_messages - len(results))
        resp = (
            gmail_service.users()
            .messages()
            .list(userId="me", q=query, maxResults=batch, pageToken=page_token)
            .execute()
        )
        ids = [m["id"] for m in resp.get("messages") or []]
        if not ids:
            break

        for mid in ids:
            if len(results) >= max_messages:
                break
            get_kw: Dict[str, Any] = {"userId": "me", "id": mid, "format": msg_format}
            if metadata_headers:
                get_kw["metadataHeaders"] = metadata_headers
            full = gmail_service.users().messages().get(**get_kw).execute()

            payload = full.get("payload") or {}
            from_name, from_email = parse_from_header(get_header(payload, "From"))
            if not from_email:
                continue
            if mailbox_email and from_email == mailbox_email:
                continue

            snippet = (full.get("snippet") or "").strip()
            if snippet_only:
                body = snippet
            else:
                try:
                    body = extract_plain_body(payload)
                except Exception:
                    body = snippet
            if not body:
                body = snippet

            results.append(
                InboundReplyMessage(
                    gmail_message_id=mid,
                    thread_id=full.get("threadId") or "",
                    from_email=from_email,
                    from_name=from_name,
                    subject=(get_header(payload, "Subject") or "").strip(),
                    received_at=_message_internal_date_iso(full),
                    snippet=snippet,
                    body_text=body,
                )
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return results
