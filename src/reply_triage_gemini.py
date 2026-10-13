"""
Gemini classification for inbound Underline outreach replies (Gmail REPLIES label).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import requests

REPLY_TYPES = frozenset(
    {
        "positive_curious",
        "not_now",
        "wrong_person",
        "unsubscribe",
        "auto_reply",
        "ooo",
        "spam",
        "ambiguous",
    }
)

LEAD_STATUSES = frozenset(
    {
        "Replied",
        "Not Interested",
        "Meeting Set",
        "In Sequence",
        "Uncontacted",
        "Bad Data/Bounced",
        "Proposal Sent",
    }
)

INTEREST_OUT_OF_OFFICE = "Out of office"
INTEREST_LEVELS = frozenset({"High", "Medium", "Low", INTEREST_OUT_OF_OFFICE})

GROUP_HINTS = frozenset({"engaged", "meeting", "disqualified", "active", "new_leads", "none"})


def _strip_json_object(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    return m.group(0) if m else text


def build_triage_prompt(
    *,
    from_email: str,
    from_name: str,
    subject: str,
    received_at: str,
    body_text: str,
    monday_company: str,
    monday_lead_status: str,
    monday_outreach_stage: str,
    monday_title: str,
) -> str:
    ctx = ""
    if monday_company:
        ctx = f"""
Monday CRM match:
- Company (pulse name): {monday_company}
- Current Lead Status: {monday_lead_status or "(empty)"}
- Outreach Stage: {monday_outreach_stage or "(empty)"}
- Contact title: {monday_title or "(empty)"}
"""
    return f"""You triage inbound email replies for The Underline (Miami public park / sponsorship outreach).

Return ONLY one JSON object (no markdown) with these keys:
- reply_type: one of {sorted(REPLY_TYPES)}
- lead_status: one of {sorted(s for s in LEAD_STATUSES if s)} — suggested Monday Lead Status after this reply
- interest_level: "High", "Medium", "Low", "Out of office", or null
- suggested_group: one of {sorted(GROUP_HINTS)} — engaged = warm reply worth follow-up; meeting = call booked or strong intent; disqualified = unsubscribe/not interested/spam; active = still in sequence but not warm; none = leave group
- next_action: short imperative for the rep (e.g. "Book 15-min call with Lia")
- next_action_date: YYYY-MM-DD or null (suggest +3 business days for warm replies)
- notes_summary: ONE or TWO short sentences for Monday Notes — plain English only, written for a salesperson. Say what the reply means and any referral/return timing. Do NOT paste the email, signatures, or metadata (no "type=", "Next:", brackets, or "Thank you for your message" boilerplate).
- apply_to_monday: boolean — false if auto_reply/ooo/spam or no CRM value
- confidence: "high", "medium", or "low"

Rules:
- auto_reply / out-of-office → reply_type ooo or auto_reply, interest_level "Out of office", lead_status Replied, apply_to_monday true (tag CRM), do not mark Meeting Set
- unsubscribe / stop / remove → reply_type unsubscribe, lead_status "Not Interested", suggested_group disqualified
- "not now" / timing → not_now, lead_status Replied, interest Medium or Low
- real interest / call request → positive_curious, lead_status Replied or Meeting Set if they proposed a time, interest High, suggested_group engaged
- wrong person / refer to colleague → wrong_person, notes who to contact
- marketing spam unrelated → spam, apply_to_monday false

Inbound message:
From: {from_name} <{from_email}>
Date: {received_at}
Subject: {subject}
{ctx}
Body:
---
{body_text[:8000]}
---
"""


def _extract_referred_email(text: str) -> str:
    for pat in (
        r"contact\s+([\w.+-]+@[\w.-]+\.\w+)",
        r"reach\s+([\w.+-]+@[\w.-]+\.\w+)",
        r"([\w.+-]+@[\w.-]+\.\w+)",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).lower()
    return ""


def crm_note_for_reply(
    reply_type: str,
    *,
    from_name: str = "",
    blob: str = "",
) -> str:
    """Human-readable Monday note when heuristics run (no Gemini)."""
    first = (from_name or "Contact").split()[0] or "Contact"
    b = blob.lower()
    if reply_type == "wrong_person":
        ref = _extract_referred_email(blob)
        if ref:
            return f"{first} is no longer with the company; they referred us to {ref}."
        return f"{first} asked us to contact someone else on their team."
    if reply_type in {"ooo", "auto_reply"}:
        if "maternity" in b:
            return f"{first} is on maternity leave; follow up after they return."
        if "traveling" in b or "out of the office" in b or "out of office" in b:
            return f"{first} is out of office; follow up after they are back."
        return f"{first} sent an automatic out-of-office reply."
    if reply_type == "unsubscribe":
        return f"{first} asked to stop outreach."
    if reply_type == "positive_curious":
        return f"{first} replied with interest; schedule a short call."
    if reply_type == "not_now":
        return f"{first} is not ready now; nurture and revisit later."
    return f"{first} replied to outreach (review thread)."


def polish_notes_summary(notes: str, *, reply_type: str, from_name: str = "", blob: str = "") -> str:
    """Ensure CRM notes are short and not raw email dumps."""
    n = re.sub(r"\s+", " ", (notes or "").strip())
    if not n or len(n) > 400:
        n = ""
    ugly = (
        n.startswith("Thank you for your message")
        or "[reply triage" in n.lower()
        or "type=" in n.lower()
        or "next:" in n.lower()
        or len(n) > 350
    )
    if ugly or not n:
        n = crm_note_for_reply(reply_type, from_name=from_name, blob=blob)
    return n[:320]


def _sanitize_error(exc: BaseException) -> str:
    msg = str(exc)
    msg = re.sub(r"key=[A-Za-z0-9_-]+", "key=***", msg)
    return msg[:200]


def heuristic_triage(
    *,
    subject: str,
    body_text: str,
    snippet: str,
) -> Dict[str, Any] | None:
    """Fast path for obvious auto-replies without calling Gemini."""
    blob = f"{subject}\n{snippet}\n{body_text}".lower()
    ooo_markers = (
        "maternity leave",
        "out of office",
        "out of the office",
        "ooo",
        "automatic reply",
        "auto-reply",
        "autoreply",
        "away from",
        "delayed response",
        "slower response",
        "traveling this week",
        "thanks for your message",
    )
    wrong_markers = (
        "no longer with",
        "no longer at",
        "has left the company",
        "is no longer",
    )
    if any(x in blob for x in ooo_markers):
        wrong = any(x in blob for x in wrong_markers)
        return normalize_triage(
            {
                "reply_type": "wrong_person" if wrong else "ooo",
                "lead_status": "Replied",
                "interest_level": None if wrong else INTEREST_OUT_OF_OFFICE,
                "suggested_group": "engaged" if wrong else "none",
                "next_action": (
                    "Follow up with referred contact"
                    if wrong
                    else "Re-send after return date; note alternate contact if given"
                ),
                "next_action_date": None,
                "notes_summary": crm_note_for_reply(
                    "wrong_person" if wrong else "ooo",
                    from_name="",
                    blob=f"{snippet}\n{body_text}",
                ),
                "apply_to_monday": True,
                "confidence": "medium",
            }
        )
    if any(x in blob for x in wrong_markers) and "please contact" in blob:
        return normalize_triage(
            {
                "reply_type": "wrong_person",
                "lead_status": "Replied",
                "interest_level": None,
                "suggested_group": "engaged",
                "next_action": "Email the referred contact",
                "next_action_date": None,
                "notes_summary": crm_note_for_reply(
                    "wrong_person",
                    blob=f"{snippet}\n{body_text}",
                ),
                "apply_to_monday": True,
                "confidence": "medium",
            }
        )
    if any(x in blob for x in ("unsubscribe", "remove me", "stop emailing", "do not contact")):
        return normalize_triage(
            {
                "reply_type": "unsubscribe",
                "lead_status": "Not Interested",
                "interest_level": None,
                "suggested_group": "disqualified",
                "next_action": "Remove from sequences",
                "next_action_date": None,
                "notes_summary": crm_note_for_reply("unsubscribe", blob=f"{snippet}\n{body_text}"),
                "apply_to_monday": True,
                "confidence": "high",
            }
        )
    return None


def classify_reply(
    *,
    api_key: str,
    model: str,
    from_email: str,
    from_name: str,
    subject: str,
    received_at: str,
    body_text: str,
    monday_company: str = "",
    monday_lead_status: str = "",
    monday_outreach_stage: str = "",
    monday_title: str = "",
    snippet: str = "",
) -> Dict[str, Any]:
    blob = f"{subject}\n{snippet}\n{body_text}"
    rules = heuristic_triage(subject=subject, body_text=body_text, snippet=snippet)
    if rules is not None:
        if from_name and rules.get("notes_summary"):
            rules["notes_summary"] = polish_notes_summary(
                rules["notes_summary"],
                reply_type=rules["reply_type"],
                from_name=from_name,
                blob=blob,
            )
        return rules

    prompt = build_triage_prompt(
        from_email=from_email,
        from_name=from_name,
        subject=subject,
        received_at=received_at,
        body_text=body_text,
        monday_company=monday_company,
        monday_lead_status=monday_lead_status,
        monday_outreach_stage=monday_outreach_stage,
        monday_title=monday_title,
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    resp = requests.post(
        url,
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.15, "maxOutputTokens": 512},
        },
        timeout=60,
    )
    if resp.status_code == 429:
        raise RuntimeError("Gemini rate limit (429); retry later or increase --sleep")
    resp.raise_for_status()
    data = resp.json()
    text = (
        (data.get("candidates") or [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
        .strip()
    )
    raw = _strip_json_object(text)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini did not return a JSON object")
    out = normalize_triage(parsed)
    out["notes_summary"] = polish_notes_summary(
        out.get("notes_summary") or "",
        reply_type=out["reply_type"],
        from_name=from_name,
        blob=blob,
    )
    return out


def normalize_triage(raw: Dict[str, Any]) -> Dict[str, Any]:
    reply_type = str(raw.get("reply_type") or "ambiguous").strip().lower()
    if reply_type not in REPLY_TYPES:
        reply_type = "ambiguous"

    lead_status = raw.get("lead_status")
    if lead_status is not None:
        lead_status = str(lead_status).strip()
        if lead_status not in LEAD_STATUSES:
            lead_status = "Replied"
    else:
        lead_status = "Replied"

    interest = raw.get("interest_level")
    if interest is not None and str(interest).strip():
        interest = str(interest).strip()
        if interest.lower() in {"out of office", "ooo", "out-of-office"}:
            interest = INTEREST_OUT_OF_OFFICE
        elif interest not in INTEREST_LEVELS:
            interest = None
    else:
        interest = None

    if reply_type in {"auto_reply", "ooo"} and not interest:
        interest = INTEREST_OUT_OF_OFFICE

    group = str(raw.get("suggested_group") or "none").strip().lower()
    if group not in GROUP_HINTS:
        group = "none"

    apply = bool(raw.get("apply_to_monday", True))
    if reply_type == "spam":
        apply = False
    elif reply_type in {"auto_reply", "ooo"}:
        apply = True

    conf = str(raw.get("confidence") or "medium").strip().lower()
    if conf not in {"high", "medium", "low"}:
        conf = "medium"

    nad = raw.get("next_action_date")
    if nad is not None and str(nad).strip():
        nad = str(nad).strip()[:10]
    else:
        nad = None

    notes = polish_notes_summary(
        str(raw.get("notes_summary") or ""),
        reply_type=reply_type,
        blob="",
    )

    return {
        "reply_type": reply_type,
        "lead_status": lead_status,
        "interest_level": interest,
        "suggested_group": group,
        "next_action": str(raw.get("next_action") or "").strip()[:500],
        "next_action_date": nad,
        "notes_summary": notes,
        "apply_to_monday": apply,
        "confidence": conf,
    }
