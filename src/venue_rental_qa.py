"""
Lightweight QA for venue-rental prospecting.

Deliberately loose vs sponsorship QA: no revenue floor, no industry allow-list,
no company-name CRM collision. Only title relevance, .gov/.edu email blocks,
and email-only Monday dedupe.
"""
from __future__ import annotations

from typing import Optional, Set, Tuple

from prospecting_qa import email_blocked, normalize_email

# Titles must match at least one of these (substring, lowercased).
VENUE_TITLE_ALLOW_SUBSTRINGS = [
    "event",
    "events",
    "meeting",
    "meetings",
    "wedding",
    "experiential",
    "producer",
    "catering",
    "conference",
    "venue",
    "program",
    "hospitality",
    "activation",
    "banquet",
    "special event",
    "association",
    "development",  # nonprofit development & events
    "planner",
    "coordinator",
]

# Only truly irrelevant junk — coordinators are ALLOWED for venue rental.
VENUE_TITLE_BLOCK_SUBSTRINGS = [
    "intern",
    "assistant to",
    " administrative assistant",
    "receptionist",
    "office manager",
    "help desk",
    "it support",
    "recruiter",
    "talent acquisition",
    "paralegal",
    "attorney",
    "counsel",
    "professor",
    "lecturer",
    "coach",
    "athletic director",
    "equipment manager",
    "store manager",
    "assistant store",
    "shift manager",
    "staffing",
    "privacy",
    "data security",
    "information security",
    " grc",
    "internal audit",
    "director of finance",
    "director, finance",
    " fp&a",
    "fp&a ",
    "financial planning",
    "controller",
    "accounting",
    "procurement",
    "software engineer",
    "data scientist",
    "devops",
]


def venue_title_gate(title: str) -> Tuple[bool, str]:
    """Allow event/meeting/wedding/hospitality titles; block obvious junk."""
    t = (title or "").strip().lower()
    if not t:
        return False, "empty_title"
    for b in VENUE_TITLE_BLOCK_SUBSTRINGS:
        if b in t:
            return False, f"title_blocked:{b.strip()}"
    if not any(a in t for a in VENUE_TITLE_ALLOW_SUBSTRINGS):
        return False, "title_not_relevant"
    return True, "ok"


def venue_email_ok(email: str, monday_emails: Set[str]) -> Tuple[bool, str]:
    """
    Email hygiene + email-only Monday dedupe.
    Returns (ok, reason). monday_emails should be the full-board normalized set.
    """
    email_n = normalize_email(email)
    if not email_n:
        return False, "no email"
    bad = email_blocked(email_n)
    if bad:
        return False, f"email QA: {bad}"
    if email_n in monday_emails:
        return False, f"email already on Monday ({email_n})"
    return True, "ok"


def normalize_person_id(person: dict) -> Optional[str]:
    pid = person.get("id") or person.get("apollo_id")
    if not pid:
        return None
    return str(pid)
