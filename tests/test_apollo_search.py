"""Direct people search and person-id dedupe. Helpers live on apollo_client."""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from apollo_client import (  # noqa: E402
    dedupe_people_by_id,
    search_people_direct,
    with_retry,
)


class _FakeApollo:
    def __init__(self) -> None:
        self.last_payload: Optional[Dict[str, Any]] = None
        self.calls = 0

    def search_people(self, data, page=1):
        self.calls += 1
        self.last_payload = dict(data)
        self.last_payload["page"] = page
        return {
            "people": [
                {"id": "p1", "title": "Event Planner"},
                {"id": "p2", "title": "Wedding Coordinator"},
            ],
            "pagination": {"total_pages": 1, "page": page},
        }


def test_direct_search_omits_org_filters() -> None:
    apollo = _FakeApollo()
    data = search_people_direct(
        apollo,
        titles=["Event Planner"],
        locations=["Miami, Florida, United States"],
        page=1,
        per_page=100,
    )
    assert data is not None
    payload = apollo.last_payload
    assert payload is not None
    assert "organization_ids" not in payload
    assert "q_organization_name" not in payload
    assert payload["person_titles"] == ["Event Planner"]
    assert payload["person_locations"] == ["Miami, Florida, United States"]
    assert payload["per_page"] == 100
    assert payload.get("contact_email_status") == ["verified"]
    assert payload.get("include_similar_titles") is True
    assert "revenue_range[min]" not in payload
    assert "organization_num_employees_ranges" not in payload


def test_direct_search_optional_budget_filters() -> None:
    apollo = _FakeApollo()
    data = search_people_direct(
        apollo,
        titles=["Director of Sponsorships"],
        locations=["Miami, Florida, United States"],
        include_similar_titles=False,
        revenue_min=10_000_000,
        employee_ranges=["51,100", "101,200", "10001+"],
    )
    assert data is not None
    payload = apollo.last_payload
    assert payload is not None
    assert payload["revenue_range[min]"] == 10_000_000
    assert payload["include_similar_titles"] is False
    ranges = payload["organization_num_employees_ranges"]
    assert ranges[0] == "51,100"
    for r in ranges:
        if r == "10001+":
            continue
        lo = int(str(r).split(",")[0])
        assert lo >= 51


def test_org_path_forwards_revenue_min() -> None:
    from apollo_client import search_orgs_then_people

    class _FakeApolloOrgs:
        def __init__(self) -> None:
            self.org_kwargs = None

        def iter_organization_ids(self, **kwargs):
            self.org_kwargs = kwargs
            return iter([])

        def search_people_by_orgs(self, **kwargs):
            raise AssertionError("no orgs, should not search people")

    apollo = _FakeApolloOrgs()
    out = search_orgs_then_people(
        apollo,
        org_keyword_tags=["consumer packaged goods"],
        org_locations=["Florida, United States"],
        person_titles=["Director of Sponsorships"],
        person_seniorities=["director"],
        employee_ranges=["51,100"],
        revenue_min=10_000_000,
        include_similar_titles=False,
    )
    assert out == []
    assert apollo.org_kwargs is not None
    assert apollo.org_kwargs["revenue_min"] == 10_000_000
    assert apollo.org_kwargs["employee_ranges"] == ["51,100"]


def test_dedupe_people_by_id() -> None:
    people = [
        {"id": "a", "title": "Event Planner"},
        {"id": "b", "title": "Wedding Planner"},
        {"id": "a", "title": "Event Planner Dup"},
        {"apollo_id": "b", "title": "Dup via apollo_id"},
        {"title": "No id"},
    ]
    out = dedupe_people_by_id(people)
    assert len(out) == 2
    assert {p["id"] for p in out} == {"a", "b"}


def test_with_retry_succeeds_after_none() -> None:
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            return None
        return {"ok": True}

    result = with_retry(flaky, max_attempts=5, base_sleep_s=0.01, label="test")
    assert result == {"ok": True}
    assert calls["n"] == 3
