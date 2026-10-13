import json
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from brand_fit_scorer import _heuristic_score  # noqa: E402
from sponsor_llm_extract import _validate_rows  # noqa: E402
from sponsor_name_qa import is_benefit_phrase, is_plausible_brand_name  # noqa: E402
from sponsor_research import filter_crm_collisions  # noqa: E402
from sponsor_tavily_context import _snippet_is_relevant  # noqa: E402
from underline_knowledge import (  # noqa: E402
    BRAND_DECK_CANDIDATES,
    LEVITT_DECK_CANDIDATES,
    build_underline_context_block,
    load_deck_excerpts,
    load_miami_events_seed,
    rotate_events,
)


def test_rotate_events_round_robin() -> None:
    events = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    picked = rotate_events(events, 2, offset=1)
    assert [e["name"] for e in picked] == ["B", "C"]


def test_rejects_benefit_phrases() -> None:
    junk = [
        "Founder education",
        "How to Use AI in Marketing",
        "Visibility across the full Tech Week calendar",
        "Executive thought leadership",
        "Community activation",
        "About Amaze:",
    ]
    for phrase in junk:
        assert is_benefit_phrase(phrase), phrase
        assert not is_plausible_brand_name(phrase, event_name="Miami Tech Week"), phrase


def test_validate_rows_accepts_real_brands() -> None:
    rows = [
        {
            "company_name": "Neutrogena",
            "sponsorship_evidence": "Official beauty and sun-care partner at Miami Swim Week with on-site activations.",
            "evidence_url": "https://example.com/partners",
        },
        {
            "company_name": "Founder education",
            "sponsorship_evidence": "Listed on sponsor page",
            "evidence_url": "",
        },
    ]
    out = _validate_rows(rows, event_name="Miami Swim Week")
    assert len(out) == 1
    assert out[0]["company_name"] == "Neutrogena"


def test_snippet_filter_drops_wrong_tech_week() -> None:
    row = {
        "title": "Tech Week marketing partners",
        "content": "Visibility across the calendar in Grand Rapids",
        "url": "https://www.techweekgr.com/partners",
    }
    assert not _snippet_is_relevant(row, "Miami Tech Week")


def test_snippet_filter_keeps_miami_sponsor_hit() -> None:
    row = {
        "title": "Miami Swim Week sponsors",
        "content": "Official partners include Neutrogena and MINI USA in Miami",
        "url": "https://paraisomiamibeach.com/partners",
    }
    assert _snippet_is_relevant(row, "Miami Swim Week")


@patch("sponsor_llm_extract.cursor_cloud_prompt")
def test_extract_sponsors_from_context(mock_cursor) -> None:
    from sponsor_llm_extract import extract_sponsors_from_context

    mock_cursor.return_value = json.dumps(
        [
            {
                "company_name": "Amaze",
                "sponsorship_evidence": "Official merchandise sponsor of Winter Music Conference 2026.",
                "evidence_url": "https://wmc.com/partners",
            }
        ]
    )
    with patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):
        out = extract_sponsors_from_context(
            "Winter Music Conference",
            {"answer": "Amaze is official merch sponsor", "snippets": []},
        )
    assert len(out) == 1
    assert out[0]["company_name"] == "Amaze"
    assert out[0]["discovery_source"] == "tavily_cursor"


def test_filter_crm_collisions() -> None:
    candidates = [{"company_name": "Fiji Water"}, {"company_name": "New Brand Co"}]
    kept, rejected = filter_crm_collisions(candidates, {"fiji water"})
    assert len(kept) == 1
    assert kept[0]["company_name"] == "New Brand Co"


def test_heuristic_score_capped_below_push_threshold() -> None:
    c = {
        "company_name": "Celsius",
        "sponsorship_evidence": "Official energy drink sponsor at Ultra Miami",
        "event_source": "Ultra Music Festival Miami",
        "evidence_url": "https://example.com",
    }
    scored = _heuristic_score(c)
    assert scored["confidence"] <= 65


def test_miami_events_seed_loads() -> None:
    events = load_miami_events_seed()
    assert len(events) >= 8
    assert any("Ultra" in (e.get("name") or "") for e in events)


def test_deck_paths_include_data_folder() -> None:
    assert any("Brand Deck" in str(p) for p in BRAND_DECK_CANDIDATES)
    assert any("Levitt" in str(p) for p in LEVITT_DECK_CANDIDATES)


def test_build_context_mentions_decks_or_placeholder() -> None:
    ctx = build_underline_context_block()
    assert "THE UNDERLINE" in ctx
    decks = load_deck_excerpts()
    if decks:
        assert "Brand Deck" in ctx or "Levitt" in ctx
    else:
        assert "Deck PDFs not found" in ctx or "Programming pillars" in ctx
