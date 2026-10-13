"""Cursor cycle dates and Monday column matching. No network."""
from __future__ import annotations

from datetime import datetime, timezone

from engine.balances import cursor_window, tavily_refresh
from engine.crm import columns_from_board


def test_cursor_window_starts_on_the_13th():
    start, end = cursor_window(datetime(2026, 10, 13, 8, tzinfo=timezone.utc))
    assert start == datetime(2026, 10, 13, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 13, tzinfo=timezone.utc)


def test_cursor_window_before_the_13th_uses_the_previous_month():
    start, end = cursor_window(datetime(2026, 10, 12, 23, tzinfo=timezone.utc))
    assert start == datetime(2026, 9, 13, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 13, tzinfo=timezone.utc)


def test_cursor_window_crosses_the_year():
    start, end = cursor_window(datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert start == datetime(2025, 12, 13, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 13, tzinfo=timezone.utc)


def test_tavily_refresh_is_the_first_of_next_month():
    assert tavily_refresh(datetime(2026, 10, 12, tzinfo=timezone.utc)) == "2026-11-01"
    assert tavily_refresh(datetime(2026, 12, 31, tzinfo=timezone.utc)) == "2027-01-01"


def test_columns_match_the_underline_board_titles():
    metadata = {
        "columns": [
            {"id": "text_mm0xjngp", "title": "First Name"},
            {"id": "text_mm0xg7qz", "title": "Last Name"},
            {"id": "email_mm0xb00t", "title": "Email"},
            {"id": "text_mm0xg2xb", "title": "Title"},
            {"id": "dropdown_mm0x5x0q", "title": "Record Type"},
            {"id": "text_mm0x49y", "title": "Seniority"},
            {"id": "text_mm0xcyag", "title": "Departments"},
            {"id": "text_mm0xt1wm", "title": "Website"},
            {"id": "text_mm0xyyzh", "title": "Person Linkedin Url"},
            {"id": "numeric_mm0x7xfb", "title": "Annual Revenue"},
            {"id": "text_mm0xkdyw", "title": "City"},
            {"id": "text_mm0xrszg", "title": "State"},
            {"id": "text_mm0x4tb7", "title": "Country"},
            {"id": "dropdown_mm0xx10b", "title": "Vertical"},
            {"id": "status", "title": "Lead Status"},
            {"id": "text_mm0xz0w2", "title": "Notes"},
        ]
    }
    mapped, missing = columns_from_board(metadata)
    assert missing == []
    assert mapped["contact_type"] == "dropdown_mm0x5x0q"
    assert mapped["linkedin"] == "text_mm0xyyzh"
    assert mapped["status"] == "status"
