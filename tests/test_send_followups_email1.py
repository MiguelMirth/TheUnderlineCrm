import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from send_followups_email1 import (  # noqa: E402
    DEFAULT_DATE_FROM,
    DEFAULT_DATE_TO,
    in_date_range,
    make_followup_body,
    parse_date,
    parse_env_date,
    resolve_date_window,
)


def test_default_date_window() -> None:
    assert DEFAULT_DATE_FROM == date(2026, 3, 25)
    assert DEFAULT_DATE_TO == date(2026, 6, 1)


def test_in_date_range_inclusive() -> None:
    start = date(2026, 3, 25)
    end = date(2026, 5, 28)
    assert in_date_range(date(2026, 3, 25), start, end)
    assert in_date_range(date(2026, 5, 28), start, end)
    assert not in_date_range(date(2026, 3, 24), start, end)
    assert not in_date_range(date(2026, 5, 29), start, end)


def test_make_followup_body_email2_copy() -> None:
    text, html = make_followup_body("Alex", "Fiji Water", deck_link="https://example.com/deck")
    assert "Hi Alex," in text
    assert "Fiji Water" in text
    assert "2M visitors a year" in text
    assert "Urban Gym" in text
    assert "https://example.com/deck" in text
    assert "15 minutes next week" in text
    assert 'href="https://example.com/deck"' in html


def test_make_followup_body_fallback_name() -> None:
    text, _ = make_followup_body("", "", deck_link="https://example.com/deck")
    assert "Hi there," in text
    assert "your team" in text


def test_parse_env_date(monkeypatch) -> None:
    monkeypatch.delenv("FOLLOWUP_DATE_FROM", raising=False)
    assert parse_env_date("FOLLOWUP_DATE_FROM", date(2026, 1, 1)) == date(2026, 1, 1)

    monkeypatch.setenv("FOLLOWUP_DATE_FROM", "2026-04-01")
    assert parse_env_date("FOLLOWUP_DATE_FROM", date(2026, 1, 1)) == date(2026, 4, 1)


def test_resolve_date_window() -> None:
    start, end = resolve_date_window(date(2026, 3, 25), date(2026, 5, 28))
    assert start == date(2026, 3, 25)
    assert end == date(2026, 5, 28)


def test_parse_date_formats() -> None:
    assert parse_date("2026-03-25") == date(2026, 3, 25)
    assert parse_date("03/25/2026") == date(2026, 3, 25)
