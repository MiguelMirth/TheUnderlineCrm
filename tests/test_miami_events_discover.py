import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from miami_events_discover import (  # noqa: E402
    merge_event_seeds,
    slug_event_id,
    _normalize_event_row,
)


def test_slug_event_id() -> None:
    assert slug_event_id("Art Basel Miami Beach") == "art_basel_miami_beach"
    assert slug_event_id("F1 Miami") == "f1_miami"


def test_merge_keeps_existing_and_adds_new() -> None:
    existing = [{"event_id": "ultra", "name": "Ultra Music Festival Miami", "search_queries": ["x"]}]
    discovered = [
        {"event_id": "new_fest", "name": "Coconut Grove Arts Festival", "search_queries": ["a", "b"]},
        {"event_id": "ultra_dup", "name": "Ultra Music Festival Miami", "search_queries": ["y"]},
    ]
    merged, new_count = merge_event_seeds(existing, discovered)
    assert new_count == 1
    assert len(merged) == 2
    assert merged[0]["name"] == "Coconut Grove Arts Festival"


def test_normalize_event_adds_sponsor_queries() -> None:
    row = _normalize_event_row({"name": "Miami Film Festival"}, year=2026)
    assert row
    assert row["event_id"] == "miami_film_festival"
    assert len(row["search_queries"]) == 2
    assert "2026" in row["search_queries"][0]
    assert "sponsor" in row["search_queries"][0].lower()
