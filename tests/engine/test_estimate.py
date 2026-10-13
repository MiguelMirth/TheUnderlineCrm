"""Cap-based estimate: upper bounds from caps, ceilings from env, blockers when a ceiling is missing or exceeded."""
from __future__ import annotations

from engine.models import resolve_caps, resolve_toggle_values
from engine.presets import PRESETS
from engine.spend import build_estimate, cap_lines


def _plan(vertical_id: str, toggles: dict | None = None, caps: dict | None = None):
    preset = PRESETS["underline"]
    vertical = preset.vertical(vertical_id)
    values = resolve_toggle_values(vertical, toggles or {})
    return preset, vertical, values, resolve_caps(vertical, caps or {})


def _provider(est, name):
    return next((p for p in est.providers if p.provider == name), None)


def test_sponsor_estimate_matches_plan_numbers(store):
    preset, vertical, values, caps = _plan("sponsor_brands")
    est = build_estimate(store, preset, vertical, values, caps)
    tavily = _provider(est, "tavily")
    cursor = _provider(est, "cursor")
    apollo = _provider(est, "apollo")
    # 4 events x 2 queries = 8 Tavily searches
    assert tavily.total == 8
    # 4 extracts + ceil(8 / 6) = 2 scoring batches + 1 employer resolve = 7
    assert cursor.total == 7
    # 8 brands x 3 org lookups = 24, plus 8 brands x 2 contacts = 16 enrich
    assert apollo.total == 40


def test_discover_new_events_adds_tavily_and_cursor_lines(store):
    preset, vertical, values, caps = _plan("sponsor_brands", {"discover_new_events": True})
    lines = cap_lines(vertical, caps, values)
    labels = [line.label for line in lines["tavily"]]
    assert any("Discover new events" in label for label in labels)
    assert any("Discover new events" in line.label for line in lines["cursor"])


def test_concert_tavily_lines_only_when_spend_evidence_is_on(store):
    preset, vertical, values, caps = _plan("concert_series")
    assert _provider(build_estimate(store, preset, vertical, values, caps), "tavily") is not None
    preset, vertical, values, caps = _plan("concert_series", {"require_spend_evidence": False})
    assert _provider(build_estimate(store, preset, vertical, values, caps), "tavily") is None


def test_concert_caps_are_upper_bounds_and_unknown_lines_stay_unknown(store):
    preset, vertical, values, caps = _plan("concert_series", caps={"target": 500})
    est = build_estimate(store, preset, vertical, values, caps)
    apollo = _provider(est, "apollo")
    enrich = next(line for line in apollo.lines if line.label == "People to enrich")
    assert enrich.units == 500
    org_survivors = next(line for line in apollo.lines if line.label == "Company lookups")
    assert org_survivors.units is None  # measured after the free probe
    # Spend-evidence searches: ceil(500 / 8) = 63 uncapped, but RUN_MAX_TAVILY_QUERIES (25) caps the run
    assert _provider(est, "tavily").total == 25
    gemini = _provider(est, "gemini")
    assert gemini.total == 25  # ceil(500 / 20) until the free probe lowers it


def test_venue_has_no_tavily_or_cursor(store):
    preset, vertical, values, caps = _plan("venue_rental")
    est = build_estimate(store, preset, vertical, values, caps)
    assert _provider(est, "tavily") is None
    assert _provider(est, "cursor") is None


def test_paid_run_is_blocked_when_ceiling_is_unset(store):
    preset, vertical, values, caps = _plan("sponsor_brands")
    est = build_estimate(store, preset, vertical, values, caps)
    assert est.can_start is False
    assert any("APOLLO_MONTHLY_CREDIT_CEILING is not set" in b for b in est.blockers)


def test_ceiling_set_allows_start(store, monkeypatch):
    monkeypatch.setenv("APOLLO_MONTHLY_CREDIT_CEILING", "1000")
    monkeypatch.setenv("TAVILY_MONTHLY_CREDIT_CEILING", "1000")
    monkeypatch.setenv("CURSOR_MONTHLY_RUN_CEILING", "1000")
    preset, vertical, values, caps = _plan("sponsor_brands")
    est = build_estimate(store, preset, vertical, values, caps)
    assert est.blockers == []
    assert est.can_start is True


def test_month_to_date_and_reserved_count_against_the_ceiling(store, monkeypatch):
    monkeypatch.setenv("APOLLO_MONTHLY_CREDIT_CEILING", "100")
    monkeypatch.setenv("TAVILY_MONTHLY_CREDIT_CEILING", "1000")
    monkeypatch.setenv("CURSOR_MONTHLY_RUN_CEILING", "1000")
    from engine.spend import utc_month

    store.ledger_append(provider="apollo", units=50, month=utc_month(), run_id=None, stage="org")
    preset, vertical, values, caps = _plan("sponsor_brands")
    est = build_estimate(store, preset, vertical, values, caps)
    # 50 spent this month + 40 for this run = 90, under 100
    assert est.can_start is True

    store.ledger_append(provider="apollo", units=20, month=utc_month(), run_id=None, stage="org")
    est = build_estimate(store, preset, vertical, values, caps)
    # 70 spent + 40 = 110, over 100
    assert est.can_start is False
    assert any("exceeds the 100 ceiling" in b for b in est.blockers)


def test_reservations_of_active_runs_count_against_the_ceiling(store, monkeypatch):
    monkeypatch.setenv("APOLLO_MONTHLY_CREDIT_CEILING", "60")
    monkeypatch.setenv("TAVILY_MONTHLY_CREDIT_CEILING", "1000")
    monkeypatch.setenv("CURSOR_MONTHLY_RUN_CEILING", "1000")
    store.create_run(
        kind="discovery",
        preset_id="underline",
        vertical_id="sponsor_brands",
        toggles={},
        caps={},
        brief="",
        started_by="x",
        reservation={"apollo": 40},
    )
    preset, vertical, values, caps = _plan("sponsor_brands")
    est = build_estimate(store, preset, vertical, values, caps)
    # 40 reserved by the queued run + 40 for this run = 80, over 60
    assert est.can_start is False
