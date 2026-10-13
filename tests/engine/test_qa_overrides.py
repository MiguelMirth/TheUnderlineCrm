"""Per-run floors for the QA predicates. Defaults must match the env reads exactly, and the engine never mutates env."""
from __future__ import annotations

import os

from concert_series_qa import concert_org_viable
from prospecting_qa import sponsor_org_viable

# $40M is under a $100M floor and under its soft floor of half that ($50M), so it fails. Against $10M it passes.
ORG = {"org_name": "Bright Cola", "org_industry": "Food & Beverages", "annual_revenue": 40_000_000}


def test_sponsor_defaults_read_env_at_call_time(monkeypatch):
    monkeypatch.setenv("PROSPECT_BRAND_MIN_ORG_REVENUE", "100000000")
    ok, _ = sponsor_org_viable(**ORG, brand_mode=True)
    assert ok is False
    monkeypatch.setenv("PROSPECT_BRAND_MIN_ORG_REVENUE", "10000000")
    ok, _ = sponsor_org_viable(**ORG, brand_mode=True)
    assert ok is True


def test_explicit_floor_overrides_env_without_touching_it(monkeypatch):
    monkeypatch.setenv("PROSPECT_BRAND_MIN_ORG_REVENUE", "10000000")
    before = os.environ.get("PROSPECT_BRAND_MIN_ORG_REVENUE")
    ok, _ = sponsor_org_viable(**ORG, brand_mode=True, min_revenue=100_000_000)
    assert ok is False
    assert os.environ.get("PROSPECT_BRAND_MIN_ORG_REVENUE") == before


def test_strict_true_overrides_env_false(monkeypatch):
    monkeypatch.setenv("PROSPECT_SPONSOR_STRICT", "false")
    # With env false, the gate is off and everything passes.
    assert sponsor_org_viable(**ORG, brand_mode=True)[0] is True
    # The engine passes strict=True explicitly, so the same org is judged strictly.
    assert sponsor_org_viable(**ORG, brand_mode=True, strict=True, min_revenue=100_000_000)[0] is False


def test_employee_floor_defaults_to_env_and_can_be_overridden(monkeypatch):
    monkeypatch.setenv("PROSPECT_MIN_ORG_EMPLOYEES", "100")
    assert sponsor_org_viable(**ORG, brand_mode=True, estimated_employees=50)[0] is False
    assert sponsor_org_viable(**ORG, brand_mode=True, estimated_employees=50, min_employees=0)[0] is True


def test_concert_floors_default_to_env_and_can_be_overridden(monkeypatch):
    monkeypatch.setenv("CONCERT_MIN_ORG_REVENUE", "10000000")
    monkeypatch.setenv("CONCERT_MIN_ORG_EMPLOYEES", "51")
    base = dict(org_name="Bright Cola", org_industry="Food & Beverages", annual_revenue=60_000_000, estimated_employees=20)
    assert concert_org_viable(**base)[0] is False  # 20 employees is under the env floor of 51
    assert concert_org_viable(**base, min_employees=10)[0] is True
    assert concert_org_viable(**base, min_employees=10, min_revenue=100_000_000)[0] is False
