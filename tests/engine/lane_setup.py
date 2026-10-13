"""Fakes for Concert and Venue lane tests. No network."""
from __future__ import annotations

from engine.crm import board_id
from engine.models import resolve_toggle_values
from engine.presets import PRESETS

PRESET = PRESETS["underline"]
BOARD = board_id(PRESET.crm)

GOOD = {
    "id": "p-good",
    "first_name": "Ann",
    "last_name_obfuscated": "Pa***",
    "title": "Director of Sponsorships",
    "city": "Miami",
    "state": "Florida",
    "country": "United States",
    "organization": {"name": "Bright Cola", "primary_domain": "brightcola.com", "industry": "Food & Beverages"},
}
BAD = {
    "id": "p-bad",
    "first_name": "Cy",
    "last_name_obfuscated": "Ro***",
    "title": "Community Relations Manager",
    "state": "Florida",
    "country": "United States",
    "organization": {"name": "Miami Foundation", "primary_domain": "miamifoundation.org"},
}
ORG = {
    "name": "Bright Cola",
    "primary_domain": "brightcola.com",
    "industry": "Food & Beverages",
    "annual_revenue": 250_000_000,
    "estimated_num_employees": 900,
}
ENRICHED = {
    "first_name": "Ann",
    "last_name": "Park",
    "title": "Director of Sponsorships",
    "email": "ann.park@brightcola.com",
    "city": "Miami",
    "state": "Florida",
    "country": "United States",
    "organization": ORG,
}
PLANNER = {
    "id": "p-plan",
    "first_name": "Ann",
    "last_name_obfuscated": "Le***",
    "title": "Event Planner",
    "city": "Miami",
    "state": "Florida",
    "country": "United States",
    "organization": {"name": "Planner Co", "primary_domain": "plannerco.com"},
}


class FakeApollo:
    def __init__(self, people: list[dict]):
        self.people = people
        self.calls: list[str] = []

    def search_people(self, data, page=1):
        self.calls.append("people")
        if self.calls.count("people") > 1:
            return {"people": [], "pagination": {"page": page, "total_pages": 1}}
        return {"people": list(self.people), "pagination": {"page": page, "total_pages": 1}}

    def search_organization_by_domain(self, domain, **kwargs):
        self.calls.append("org")
        return {"organizations": [dict(ORG)]}

    def search_organization_by_name(self, name, **kwargs):
        self.calls.append("org")
        return {"organizations": [dict(ORG, name=name)]}

    def search_companies(self, data, page=1):
        self.calls.append("org_page")
        return {"organizations": [], "pagination": {"page": page, "total_pages": 1}}

    def enrich_person(self, person_id):
        self.calls.append("enrich")
        return dict(ENRICHED, id=person_id)


def tavily_pass(query: str) -> dict:
    return {
        "results": [
            {
                "title": "Bright Cola official sponsor of a festival",
                "content": "Bright Cola is the official sponsor of the festival",
                "url": "https://example.com/sponsor",
            }
        ]
    }


def gemini_pass(vertical_id: str, rows: list[dict]) -> list[dict]:
    return [
        {
            "row_id": row["row_id"],
            "verdict": "pass",
            "reason": "paid buyer",
            "region": "Florida",
            "sector": "beverage",
            "sponsorship_evidence": "yes",
        }
        for row in rows
    ]


def seed(store, monkeypatch, tmp_path):
    from engine import crm

    monkeypatch.setenv("CRM_SNAPSHOT_TTL_HOURS", "12")
    empty = tmp_path / "blacklist.txt"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(crm, "blacklist_path", lambda preset: empty)
    for name, value in (
        ("APOLLO_MONTHLY_CREDIT_CEILING", "100"),
        ("TAVILY_MONTHLY_CREDIT_CEILING", "100"),
        ("GEMINI_MONTHLY_REQUEST_CEILING", "100"),
        ("GEMINI_API_KEY", "test-key"),
    ):
        monkeypatch.setenv(name, value)
    store.crm_snapshot_put(BOARD, {"board_id": BOARD, "rows": []})
    return store


def queue(store, vertical_id: str, **toggles):
    vertical = PRESET.vertical(vertical_id)
    overrides: dict = {"org_path": False, **toggles}
    if vertical_id == "concert_series":
        overrides.setdefault("max_tier", 1)
    values = resolve_toggle_values(vertical, overrides)
    caps = {"target": 5, "max_pages": 1, "title_chunk": 50, "org_pages": 1}
    return store.create_run(
        kind="discovery",
        preset_id="underline",
        vertical_id=vertical_id,
        toggles=values,
        caps=caps,
        brief="",
        started_by="tester",
        reservation={"apollo": 20, "tavily": 5, "gemini": 5},
    )
