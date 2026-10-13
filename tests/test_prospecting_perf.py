"""Performance-path helpers: dedupe, parallel map, pre-enrich gates."""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from apollo_contact_rank import should_enrich_person  # noqa: E402
from prospecting_parallel import map_parallel, research_worker_count  # noqa: E402
from sponsor_research import dedupe_candidates_by_company  # noqa: E402


def test_dedupe_candidates_keeps_best_evidence() -> None:
    rows = [
        {
            "company_name": "Santander",
            "sponsorship_evidence": "short",
            "event_source": "A",
        },
        {
            "company_name": "Santander",
            "sponsorship_evidence": "official presenting partner with long evidence text here",
            "evidence_url": "https://example.com/x",
            "discovery_source": "tavily_cursor",
            "event_source": "B",
        },
        {
            "company_name": "Oakberry",
            "sponsorship_evidence": "acai shop near CocoWalk with corporate office presence",
            "event_source": "C",
        },
    ]
    out = dedupe_candidates_by_company(rows)
    assert len(out) == 2
    santander = next(r for r in out if r["company_name"] == "Santander")
    assert santander["event_source"] == "B"
    assert any(r["company_name"] == "Oakberry" for r in out)


def test_map_parallel_preserves_order() -> None:
    def slow_square(n: int) -> int:
        time.sleep(0.05 if n == 1 else 0.01)
        return n * n

    assert map_parallel([1, 2, 3, 4], slow_square, max_workers=3) == [1, 4, 9, 16]


def test_research_worker_count_clamped(monkeypatch) -> None:
    monkeypatch.setenv("PROSPECT_RESEARCH_WORKERS", "99")
    assert research_worker_count() == 8
    monkeypatch.setenv("PROSPECT_RESEARCH_WORKERS", "0")
    assert research_worker_count() == 1


def test_should_enrich_skips_weak_title_before_api() -> None:
    ok, reason, pts = should_enrich_person(
        {"title": "Vice President", "country": "United States"},
        shelf_brand="Santander",
        research_mode=True,
        min_title_score=45,
    )
    assert ok is False
    assert "title fit too weak" in reason
    assert pts < 45


def test_should_enrich_skips_non_us_tagged() -> None:
    ok, reason, _ = should_enrich_person(
        {"title": "Director of Brand Partnerships", "country": "Brazil"},
        shelf_brand="Oakberry",
        research_mode=True,
    )
    assert ok is False
    assert "person_country_not_us" in reason


def test_should_enrich_accepts_sponsorship_title() -> None:
    ok, reason, pts = should_enrich_person(
        {
            "title": "Vice President Sponsorships and Sports Marketing",
            "country": "United States",
        },
        shelf_brand="Mars",
        research_mode=True,
    )
    assert ok is True
    assert reason == ""
    assert pts >= 45
