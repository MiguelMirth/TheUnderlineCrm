"""Tavily spend-evidence heuristics (no network)."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from concert_series_spend import (  # noqa: E402
    CACHE_VERSION,
    SPEND_AMBIGUOUS,
    SPEND_FAIL,
    SPEND_PASS,
    ConcertSpendCache,
    brand_mentioned,
    classify_spend_text,
    evidence_from_tavily_response,
    spend_search_query,
    spend_search_query_batch,
)


def test_official_festival_sponsor_passes() -> None:
    verdict, reason = classify_spend_text(
        "Acme Snacks is the official festival sponsor of Ultra Music Festival 2026."
    )
    assert verdict == SPEND_PASS
    assert "official sponsor" in reason or "festival sponsor" in reason


def test_community_partner_in_kind_fails() -> None:
    fail_blob = (
        "Acme Snacks is a proud community partner providing in-kind donations "
        "and serving as a media partner of the neighborhood series."
    )
    verdict, reason = classify_spend_text(fail_blob)
    assert verdict == SPEND_FAIL
    assert "collab_phrase" in reason


def test_proud_partner_without_sponsor_language_fails() -> None:
    verdict, _ = classify_spend_text(
        "We are a proud partner of the local arts collaborative."
    )
    assert verdict == SPEND_FAIL


def test_empty_and_unrelated_are_ambiguous() -> None:
    assert classify_spend_text("")[0] == SPEND_AMBIGUOUS
    assert classify_spend_text("Acme Snacks launched a new flavor in Miami.")[0] == (
        SPEND_AMBIGUOUS
    )


def test_official_sponsor_wins_over_community_partner() -> None:
    verdict, _ = classify_spend_text(
        "Red Bull is the official sponsor of the series and a community partner "
        "of the neighborhood cleanup."
    )
    assert verdict == SPEND_PASS


def test_spend_query_quotes_brand() -> None:
    q = spend_search_query("Red Bull")
    assert '"Red Bull"' in q
    assert "official sponsor" in q.lower() or "title sponsor" in q.lower()


def test_batch_query_lists_all_brands() -> None:
    q = spend_search_query_batch(["Red Bull", "Subway", "Hertz"])
    assert '"Red Bull"' in q
    assert '"Subway"' in q
    assert '"Hertz"' in q


def test_brand_slice_does_not_leak_pass_to_other_company() -> None:
    from concert_series_spend import company_spend_key

    resp = {
        "results": [
            {
                "title": "Red Bull named official sponsor of Ultra Music Festival",
                "content": "Red Bull is the official sponsor of the festival.",
                "url": "https://example.com/redbull",
            }
        ]
    }
    out = evidence_from_tavily_response(
        ["Red Bull", "Local HVAC Co"],
        resp,
        query="test",
    )
    assert out[company_spend_key("Red Bull")].verdict == SPEND_PASS
    assert out[company_spend_key("Local HVAC Co")].verdict == SPEND_AMBIGUOUS


def test_short_brand_needs_word_boundary() -> None:
    assert brand_mentioned("Citi", "Citi is the official sponsor of the Open")
    assert not brand_mentioned("Citi", "The citizenship program sponsored a booth")


def test_cache_is_per_company(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_chunks(chunks, *, concurrency=3):
        calls["n"] += 1
        from concert_series_spend import SpendEvidence, company_spend_key

        out = {}
        for chunk in chunks:
            for name in chunk:
                out[company_spend_key(name)] = SpendEvidence(
                    verdict=SPEND_PASS,
                    reason="paid_phrase:official sponsor",
                    notes="ok",
                )
        return out, float(len(chunks))

    monkeypatch.setattr("concert_series_spend.search_brand_chunks", fake_chunks)
    cache = ConcertSpendCache(enabled=True, cache_path="")
    a = cache.evaluate("Acme Snacks")
    b = cache.evaluate("Acme Snacks, Inc")
    assert a.verdict == SPEND_PASS
    assert b.cached is True
    assert calls["n"] == 1
    assert cache.stats["tavily_calls"] == 1


def test_ensure_many_one_search_per_batch(monkeypatch) -> None:
    seen_chunks: list[list[str]] = []

    def fake_chunks(chunks, *, concurrency=3):
        seen_chunks.extend(chunks)
        from concert_series_spend import SpendEvidence, company_spend_key

        out = {}
        for chunk in chunks:
            for name in chunk:
                out[company_spend_key(name)] = SpendEvidence(
                    verdict=SPEND_AMBIGUOUS, reason="no_snippets"
                )
        return out, float(len(chunks))

    monkeypatch.setattr("concert_series_spend.search_brand_chunks", fake_chunks)
    monkeypatch.setenv("CONCERT_SPEND_BATCH_SIZE", "8")
    cache = ConcertSpendCache(enabled=True, cache_path="")
    brands = [f"Brand {i}" for i in range(8)]
    cache.ensure_many(brands)
    assert len(seen_chunks) == 1
    assert len(seen_chunks[0]) == 8
    assert cache.stats["tavily_calls"] == 1
    assert cache.stats["tavily_credits"] == 1.0
    assert cache.stats["brands_looked_up"] == 8


def test_disk_cache_roundtrip(tmp_path, monkeypatch) -> None:
    path = str(tmp_path / "spend.json")
    calls = {"n": 0}

    def fake_chunks(chunks, *, concurrency=3):
        calls["n"] += 1
        from concert_series_spend import SpendEvidence, company_spend_key

        out = {}
        for chunk in chunks:
            for name in chunk:
                out[company_spend_key(name)] = SpendEvidence(
                    verdict=SPEND_PASS, reason="paid_phrase:official sponsor", notes="cached"
                )
        return out, 1.0

    monkeypatch.setattr("concert_series_spend.search_brand_chunks", fake_chunks)
    cache = ConcertSpendCache(enabled=True, cache_path=path)
    cache.ensure_many(["Red Bull"])
    assert calls["n"] == 1
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["_version"] == CACHE_VERSION
    assert "red bull" in raw["entries"]

    cache2 = ConcertSpendCache(enabled=True, cache_path=path)
    ev = cache2.evaluate("Red Bull")
    assert ev.verdict == SPEND_PASS
    assert ev.cached is True
    assert calls["n"] == 1
