"""Tests for venue_rental_qa — loosened title gate + email-only dedupe."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from venue_rental_qa import (  # noqa: E402
    normalize_person_id,
    venue_email_ok,
    venue_title_gate,
)


def test_coordinator_title_passes() -> None:
    ok, reason = venue_title_gate("Special Events Coordinator")
    assert ok, reason
    ok2, _ = venue_title_gate("Wedding Coordinator")
    assert ok2
    ok3, _ = venue_title_gate("Event Coordinator")
    assert ok3


def test_planner_and_director_pass() -> None:
    assert venue_title_gate("Event Planner")[0]
    assert venue_title_gate("Director of Events")[0]
    assert venue_title_gate("Wedding Planner")[0]
    assert venue_title_gate("Meeting & Events Manager")[0]


def test_intern_and_it_blocked() -> None:
    ok, reason = venue_title_gate("Events Intern")
    assert not ok
    assert "intern" in reason
    ok2, reason2 = venue_title_gate("IT Support Specialist")
    assert not ok2
    assert "it support" in reason2 or "title_not_relevant" in reason2


def test_irrelevant_title_blocked() -> None:
    ok, reason = venue_title_gate("Software Engineer")
    assert not ok
    ok2, _ = venue_title_gate("VP of Sales")
    assert not ok2  # no event/meeting/etc token


def test_empty_title_blocked() -> None:
    ok, reason = venue_title_gate("")
    assert not ok
    assert reason == "empty_title"


def test_email_dedupe_only() -> None:
    monday = {"alice@example.com", "bob@acme.com"}
    ok, reason = venue_email_ok("alice@example.com", monday)
    assert not ok
    assert "already on Monday" in reason

    ok2, _ = venue_email_ok("new.person@agency.com", monday)
    assert ok2


def test_gov_email_blocked() -> None:
    ok, reason = venue_email_ok("planner@miami.gov", set())
    assert not ok
    assert "email QA" in reason or "email_domain" in reason


def test_no_email() -> None:
    ok, reason = venue_email_ok("", set())
    assert not ok
    assert reason == "no email"


def test_normalize_person_id() -> None:
    assert normalize_person_id({"id": "abc"}) == "abc"
    assert normalize_person_id({"apollo_id": 123}) == "123"
    assert normalize_person_id({}) is None
