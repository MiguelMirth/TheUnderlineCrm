"""Tests for venue rental Email 1 body + subject."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from email_outreach import (  # noqa: E402
    make_venue_rental_email1_body,
    venue_rental_email1_subject,
)


def test_venue_rental_subject() -> None:
    assert venue_rental_email1_subject("Acme Events") == "The Underline Miami + Acme Events"
    assert "your team" in venue_rental_email1_subject("")


def test_venue_rental_body_links_deck_on_underline() -> None:
    deck = "https://docsend.com/view/zn4yktywm25267jd"
    text, html = make_venue_rental_email1_body("Lia", "Acme", deck_link=deck)
    assert text.startswith("Hi Lia,")
    assert f"The Underline ({deck})" in text
    assert "Lululemon Global Run Day" in text
    assert "Porsche VIP Event" in text
    assert f'<a href="{deck}">The Underline</a>' in html
    assert "Best," in text
    # Signature is appended by Gmail sender — not in body
    assert "Francesca" not in text


def test_venue_rental_body_fallback_without_deck() -> None:
    text, html = make_venue_rental_email1_body("Alex", deck_link="")
    assert "The Underline [DECK LINK]" in text
    assert "<a href=" not in html or "The Underline" in html
