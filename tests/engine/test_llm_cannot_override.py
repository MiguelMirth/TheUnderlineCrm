"""A Gemini pass cannot repair a failed gate, and a Gemini fail cannot be approved."""
from __future__ import annotations

from lane_setup import BAD, GOOD, FakeApollo, queue, seed

from engine import apollo_lane, llm_qa
from engine.gates import approvable
from engine.pipeline import execute_run


def _run(store, monkeypatch, tmp_path, people, verdict: str):
    seed(store, monkeypatch, tmp_path)
    apollo = FakeApollo(people)

    def gemini(vertical_id: str, rows: list[dict]) -> list[dict]:
        return [
            {
                "row_id": row["row_id"],
                "verdict": verdict,
                "reason": "model said so",
                "region": "Florida",
                "sector": "beverage",
                "sponsorship_evidence": "yes",
            }
            for row in rows
        ]

    monkeypatch.setattr(apollo_lane, "apollo_factory", lambda: apollo)
    monkeypatch.setattr(apollo_lane, "tavily_factory", lambda query: {
        "results": [{"title": "Bright Cola official sponsor", "content": "Bright Cola official sponsor of a festival", "url": "https://example.com"}]
    })
    monkeypatch.setattr(llm_qa, "generate_batch", gemini)
    run = queue(store, "concert_series")
    execute_run(store, store.claim_next_queued())
    return run, store.list_leads(run["id"]), apollo


def test_a_pass_does_not_save_a_failed_title(store, monkeypatch, tmp_path):
    _run_row, leads, _apollo = _run(store, monkeypatch, tmp_path, [BAD], "pass")
    assert leads[0]["state"] == "qa_failed"
    assert leads[0]["llm"] is None
    assert approvable(leads[0])[0] is False


def test_a_fail_is_not_approvable(store, monkeypatch, tmp_path):
    _run_row, leads, _apollo = _run(store, monkeypatch, tmp_path, [GOOD], "fail")
    assert leads[0]["state"] == "llm_failed"
    assert approvable(leads[0])[0] is False


def test_a_model_error_is_a_flag_and_does_not_enrich(store, monkeypatch, tmp_path):
    seed(store, monkeypatch, tmp_path)
    apollo = FakeApollo([GOOD])

    def boom(vertical_id: str, rows: list[dict]) -> list[dict]:
        raise RuntimeError("model down")

    monkeypatch.setattr(apollo_lane, "apollo_factory", lambda: apollo)
    monkeypatch.setattr(apollo_lane, "tavily_factory", lambda query: {
        "results": [{"title": "Bright Cola official sponsor", "content": "Bright Cola official sponsor of a festival", "url": "https://example.com"}]
    })
    monkeypatch.setattr(llm_qa, "generate_batch", boom)
    run = queue(store, "concert_series")
    execute_run(store, store.claim_next_queued())
    lead = store.list_leads(run["id"])[0]
    assert lead["state"] == "llm_failed"
    assert lead["llm"]["verdict"] == "flag"
    assert lead["llm"]["reason"] == "LLM unavailable"
    assert "enrich" not in apollo.calls
