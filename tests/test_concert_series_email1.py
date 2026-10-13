"""Tests for Concert Series Email 1 body + subject."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from email_outreach import (  # noqa: E402
    concert_series_email1_subject,
    make_concert_series_email1_body,
)


def test_concert_series_subject() -> None:
    assert (
        concert_series_email1_subject("Red Bull")
        == "The Underline + Red Bull | Miami Music Series"
    )
    assert "your team" in concert_series_email1_subject("")


def test_concert_series_body_has_tentpoles_and_company() -> None:
    text, html = make_concert_series_email1_body("Lia", "Red Bull")
    assert text.startswith("Hi Lia,")
    assert "Red Bull" in text
    assert "Caribbean Carnival" in text
    assert "October 30-31" in text or "October 30–31" in text
    assert "Miami Music Series" in text
    assert "I'd love to share the deck" in text or "I’d love to share the deck" in text
    assert "Red Bull" in html
    assert "Best," in text


def test_concert_series_body_has_no_deck_url() -> None:
    text, html = make_concert_series_email1_body(
        "Alex", "Acme", deck_link="https://docsend.com/view/should-not-appear"
    )
    assert "docsend.com" not in text
    assert "docsend.com" not in html
    assert "<a href=" not in html
    assert "we emailed" not in text.lower()
    assert "Francesca" not in text
