"""
Slack DMs to Lia after Underline outreach / prospecting batches.

Auth (prefer user token so the DM appears from Miguel's Slack account):
  SLACK_USER_TOKEN   — xoxp-… (scopes: chat:write, im:write, users:read.email)
  SLACK_BOT_TOKEN    — xoxb-… fallback (appears as the app)

Recipient:
  SLACK_LIA_USER_ID  — preferred (U…)
  SLACK_LIA_EMAIL    — default lia@knowyourmirth.com (users.lookupByEmail)

Optional:
  SLACK_NOTIFY=false — disable without removing tokens
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

import requests

SLACK_API = "https://slack.com/api"
DEFAULT_LIA_EMAIL = "lia@knowyourmirth.com"
EMAIL_PREVIEW_LIMIT = 20


def slack_notify_enabled() -> bool:
    if os.getenv("SLACK_NOTIFY", "true").lower() in ("0", "false", "no", "off"):
        return False
    return bool(_slack_token())


def _slack_token() -> str:
    return (
        os.getenv("SLACK_USER_TOKEN", "").strip()
        or os.getenv("SLACK_BOT_TOKEN", "").strip()
    )


def _lia_user_id() -> str:
    return os.getenv("SLACK_LIA_USER_ID", "").strip()


def _lia_email() -> str:
    return (os.getenv("SLACK_LIA_EMAIL", "").strip() or DEFAULT_LIA_EMAIL).lower()


def _api(
    method: str,
    *,
    token: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resp = requests.post(
        f"{SLACK_API}/{method}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json=payload or {},
        params=params or None,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {data.get('error', data)}")
    return data


def resolve_lia_user_id(token: Optional[str] = None) -> str:
    """Return Lia's Slack user id from env or email lookup."""
    cached = _lia_user_id()
    if cached:
        return cached
    tok = token or _slack_token()
    if not tok:
        raise RuntimeError("Missing SLACK_USER_TOKEN / SLACK_BOT_TOKEN")
    # lookupByEmail expects email as a query/form field
    data = _api(
        "users.lookupByEmail",
        token=tok,
        params={"email": _lia_email()},
    )
    uid = (data.get("user") or {}).get("id") or ""
    if not uid:
        raise RuntimeError(f"Could not resolve Slack user for {_lia_email()}")
    return uid


def send_dm_to_lia(text: str, *, token: Optional[str] = None) -> bool:
    """
    DM Lia. Returns True on success.
    Soft-fails (prints warning, returns False) when Slack is disabled or errors.
    """
    if not slack_notify_enabled():
        print("Slack notify skipped (disabled or no token).")
        return False
    tok = token or _slack_token()
    try:
        user_id = resolve_lia_user_id(tok)
        # Open / reuse DM channel, then post — works for user and bot tokens.
        opened = _api("conversations.open", token=tok, payload={"users": user_id})
        channel = (opened.get("channel") or {}).get("id")
        if not channel:
            raise RuntimeError("conversations.open returned no channel")
        _api("chat.postMessage", token=tok, payload={"channel": channel, "text": text})
        print(f"Slack: notified Lia ({user_id}).")
        return True
    except Exception as e:
        print(f"Slack notify failed (continuing): {e}")
        return False


def format_email_batch_message(
    *,
    stage_label: str,
    recipients: Sequence[Dict[str, str]],
    total_sent: Optional[int] = None,
    preview_limit: int = EMAIL_PREVIEW_LIMIT,
) -> str:
    """
    recipients items: first_name, company_name, email (any may be empty).
    Lists the first ``preview_limit`` people.
    """
    n = total_sent if total_sent is not None else len(recipients)
    lines = [
        f"Underline outreach — *{stage_label}*",
        f"Sent *{n}* email{'s' if n != 1 else ''}.",
        "",
    ]
    if not recipients:
        lines.append("_No recipient details captured._")
        return "\n".join(lines)

    preview = list(recipients)[:preview_limit]
    lines.append(f"First {len(preview)} recipient{'s' if len(preview) != 1 else ''}:")
    for i, r in enumerate(preview, 1):
        name = (r.get("first_name") or "").strip() or "—"
        company = (r.get("company_name") or "").strip() or "—"
        email = (r.get("email") or "").strip()
        suffix = f" (`{email}`)" if email else ""
        lines.append(f"{i}. {name} — {company}{suffix}")

    remaining = n - len(preview)
    if remaining > 0:
        lines.append(f"_…and {remaining} more._")
    return "\n".join(lines)


def format_monday_push_message(
    *,
    contacts_pushed: int,
    company_names: Sequence[str],
    board_label: str = "New Leads",
) -> str:
    """Summarize a live Monday push — company names only, not every contact."""
    unique = list(dict.fromkeys([(c or "").strip() for c in company_names if (c or "").strip()]))
    lines = [
        "Underline prospecting — Monday push",
        f"Pushed *{contacts_pushed}* contact{'s' if contacts_pushed != 1 else ''} "
        f"to *{board_label}*.",
        "",
    ]
    if not unique:
        lines.append("_No company names recorded._")
        return "\n".join(lines)

    lines.append(f"Companies added ({len(unique)}):")
    for name in unique:
        lines.append(f"• {name}")
    return "\n".join(lines)


def notify_email_batch(
    *,
    stage_label: str,
    recipients: Sequence[Dict[str, str]],
    total_sent: Optional[int] = None,
) -> bool:
    if not recipients and not (total_sent and total_sent > 0):
        return False
    text = format_email_batch_message(
        stage_label=stage_label,
        recipients=recipients,
        total_sent=total_sent,
    )
    return send_dm_to_lia(text)


def notify_monday_push(
    *,
    contacts_pushed: int,
    company_names: Sequence[str],
    board_label: str = "New Leads",
) -> bool:
    if contacts_pushed <= 0:
        return False
    text = format_monday_push_message(
        contacts_pushed=contacts_pushed,
        company_names=company_names,
        board_label=board_label,
    )
    return send_dm_to_lia(text)
