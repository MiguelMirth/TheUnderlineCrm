"""Sponsor research spends only after the free gates, and enrich skips rejected brands."""
from __future__ import annotations

from lane_setup import BOARD, seed

from engine import research_lane
from engine.presets import PRESETS
from engine.spend import Meter

PRESET = PRESETS["underline"]


class ResearchApollo:
    def __init__(self) -> None:
        self.domains: list[str] = []
        self.enriched: list[str] = []

    def search_organization_by_domain(self, domain, **kwargs):
        self.domains.append(domain)
        name = "Bright Cola" if "bright" in domain else "Night Lime"
        return {
            "organizations": [
                {
                    "id": f"org-{domain}",
                    "name": name,
                    "primary_domain": domain,
                    "website_url": f"https://{domain}",
                    "industry": "Food & Beverages",
                    "annual_revenue": 250_000_000,
                    "estimated_num_employees": 900,
                    "city": "New York",
                    "state": "New York",
                    "country": "United States",
                }
            ]
        }

    def search_organization_by_name(self, name, **kwargs):
        self.domains.append(f"name:{name}")
        return {"organizations": []}

    def search_people(self, data, page=1):
        org_id = (data.get("organization_ids") or ["x"])[0]
        assert data.get("person_locations"), "Florida (or US) person locations are required"
        return {
            "people": [
                {
                    "id": f"person-{org_id}",
                    "first_name": "Ann",
                    "last_name_obfuscated": "Pa***",
                    "title": "Director of Sponsorships",
                    "city": "Miami",
                    "state": "Florida",
                    "country": "United States",
                    "has_email": True,
                    "organization": {"id": org_id},
                }
            ],
            "pagination": {"total_pages": 1},
        }

    def enrich_person(self, person_id):
        self.enriched.append(person_id)
        return {
            "id": person_id,
            "first_name": "Ann",
            "last_name": "Park",
            "title": "Director of Sponsorships",
            "email": f"{person_id}@brightcola.com",
            "city": "Miami",
            "state": "Florida",
            "country": "United States",
            "seniority": "director",
            "linkedin_url": "https://linkedin.com/in/ann",
            "organization": {
                "name": "Bright Cola",
                "industry": "Food & Beverages",
                "annual_revenue": 250_000_000,
                "estimated_num_employees": 900,
                "website_url": "https://brightcola.com",
                "city": "New York",
                "state": "New York",
                "country": "United States",
            },
        }


def _arm(monkeypatch, store, tmp_path):
    seed(store, monkeypatch, tmp_path)
    monkeypatch.setenv("CURSOR_MONTHLY_RUN_CEILING", "50")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("CURSOR_API_KEY", "cursor-test")
    monkeypatch.setenv("APOLLO_API_KEY", "apollo-test")
    monkeypatch.delenv("CURSOR_COMPOSER_FAST", raising=False)
    monkeypatch.setenv("CURSOR_RESEARCH_MODEL", "composer-2.5")
    store.crm_snapshot_put(
        BOARD,
        {"board_id": BOARD, "rows": [{"name": "Blocked Co", "email": "", "website": "", "status": "", "group": ""}]},
    )


def _patch_sources(monkeypatch, brands: list[dict], calls: list[str]):
    monkeypatch.setattr(
        research_lane,
        "load_source_rows",
        lambda vertical, caps: [{"name": "Test Fest", "event_id": "test-fest", "search_queries": ["test fest sponsors"]}],
    )

    def gather(name, queries):
        calls.append("gather")
        return {"answer": "sponsors", "snippets": []}

    def extract(name, context):
        calls.append("extract")
        return brands

    def score(candidates):
        calls.append("score:" + ",".join(row.get("company_name", "") for row in candidates))
        return [
            {**row, "confidence": 90, "reject": False, "vertical": "Lifestyle + Premium Beverage + Entertainment"}
            for row in candidates
        ], "cursor_cloud"

    def employers(targets):
        calls.append("employers")
        return targets

    monkeypatch.setattr(research_lane, "gather_context", gather)
    monkeypatch.setattr(research_lane, "extract_brands", extract)
    monkeypatch.setattr(research_lane, "score_brands", score)
    monkeypatch.setattr(research_lane, "resolve_employers", employers)


def _queue(store, **toggles):
    vertical = PRESET.vertical("sponsor_brands")
    from engine.models import resolve_toggle_values

    values = resolve_toggle_values(vertical, toggles)
    return store.create_run(
        kind="discovery",
        preset_id="underline",
        vertical_id="sponsor_brands",
        toggles=values,
        caps={"events": 1, "brands": 4, "queries_per_source": 1},
        brief="",
        started_by="tester",
        reservation={"apollo": 30, "tavily": 10, "cursor": 10},
    )


def test_org_lookup_and_scoring_skip_a_blocked_brand(store, monkeypatch, tmp_path):
    _arm(monkeypatch, store, tmp_path)
    calls: list[str] = []
    _patch_sources(
        monkeypatch,
        [
            {"company_name": "Bright Cola", "sponsorship_evidence": "official sponsor of the festival", "evidence_url": "https://brightcola.com/a"},
            {"company_name": "Blocked Co", "sponsorship_evidence": "official sponsor", "evidence_url": "https://blocked.example/a"},
        ],
        calls,
    )
    discovered: list[str] = []
    monkeypatch.setattr(research_lane, "run_discover", lambda *args, **kwargs: discovered.append("yes") or "no")
    apollo = ResearchApollo()
    monkeypatch.setattr(research_lane, "make_apollo", lambda: apollo)
    run = _queue(store)
    summary = research_lane.research_source(store, run)
    assert summary == "shortlist 1"
    assert "discover" not in "".join(discovered) or discovered == []
    assert discovered == []
    assert "blockedco.com" not in apollo.domains
    assert any(domain.startswith("brightcola") for domain in apollo.domains)
    assert calls.index("gather") < calls.index("extract") < calls.index("score:Bright Cola")
    states = {lead["shelf_brand"]: lead["state"] for lead in store.list_leads(run["id"])}
    assert states["Blocked Co"] == "blocked"
    assert states["Bright Cola"] == "shortlisted"


def test_rejected_brand_is_not_enriched(store, monkeypatch, tmp_path):
    _arm(monkeypatch, store, tmp_path)
    _patch_sources(
        monkeypatch,
        [
            {"company_name": "Bright Cola", "sponsorship_evidence": "official sponsor of the festival", "evidence_url": "https://brightcola.com/a"},
            {"company_name": "Night Lime", "sponsorship_evidence": "title partner of the festival", "evidence_url": "https://nightlime.com/a"},
        ],
        [],
    )
    apollo = ResearchApollo()
    monkeypatch.setattr(research_lane, "make_apollo", lambda: apollo)
    run = _queue(store)
    research_lane.research_source(store, run)
    night = next(lead for lead in store.list_leads(run["id"]) if lead["shelf_brand"] == "Night Lime")
    store.update_lead(night["id"], state="rejected")
    fresh = store.get_run(run["id"])
    assert fresh is not None
    fresh["stage"] = 6
    summary = research_lane.research_source(store, fresh)
    assert summary == "enriched 1"
    assert apollo.enriched == ["person-org-brightcola.com"]
    bright = next(lead for lead in store.list_leads(run["id"]) if lead["shelf_brand"] == "Bright Cola" and lead["email"])
    assert bright["state"] == "needs_review"
    assert bright["person"]["state"] == "Florida"
    assert bright["person"]["organization"]["state"] == "New York"


def test_discover_toggle_runs_and_brief_adds_a_search(store, monkeypatch, tmp_path):
    _arm(monkeypatch, store, tmp_path)
    calls: list[str] = []
    _patch_sources(monkeypatch, [], calls)

    def discover(store, meter, seed_path):
        calls.append("discover")
        return "discover skipped in test"

    def brief(text):
        calls.append("brief:" + text)
        return {"answer": text, "results": []}

    monkeypatch.setattr(research_lane, "run_discover", discover)
    monkeypatch.setattr(research_lane, "search_brief", brief)
    monkeypatch.setattr(research_lane, "make_apollo", lambda: ResearchApollo())
    run = _queue(store, discover_new_events=True)
    run["brief"] = "art week hospitality"
    research_lane.research_source(store, run)
    assert "discover" in calls
    assert "brief:art week hospitality" in calls


def test_discover_charges_tavily_and_cursor(store, monkeypatch, tmp_path):
    _arm(monkeypatch, store, tmp_path)
    seed_path = tmp_path / "events.json"
    seed_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        "miami_events_discover.gather_miami_events_research",
        lambda **kwargs: {"answer": "a festival", "snippets": []},
    )
    monkeypatch.setattr(
        "miami_events_discover.extract_events_from_research",
        lambda *args, **kwargs: [{"name": "New Fest", "event_id": "new-fest"}],
    )
    run = store.create_run(
        kind="discovery",
        preset_id="underline",
        vertical_id="sponsor_brands",
        toggles={},
        caps={},
        brief="",
        started_by="tester",
        reservation={"tavily": 10, "cursor": 5, "apollo": 1},
    )
    meter = Meter(store, run["id"], "source")
    note = research_lane.run_discover(store, meter, str(seed_path))
    assert "added 1" in note
    assert store.ledger_run_total(run["id"], "tavily") == 8
    assert store.ledger_run_total(run["id"], "cursor") == 1
    saved = seed_path.read_text(encoding="utf-8")
    assert "New Fest" in saved
