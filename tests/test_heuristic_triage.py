import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from reply_triage_gemini import heuristic_triage  # noqa: E402


def test_heuristic_wrong_person() -> None:
    out = heuristic_triage(
        subject="Re: partnership",
        snippet="Trisha is no longer with Docker. Please contact terri.avnaim@docker.com",
        body_text="",
    )
    assert out is not None
    assert out["reply_type"] == "wrong_person"
    assert out["apply_to_monday"] is True
    assert "terri.avnaim@docker.com" in out["notes_summary"]
    assert "Reply triage" not in out["notes_summary"]


def test_heuristic_ooo() -> None:
    out = heuristic_triage(
        subject="Maternity Leave",
        snippet="I am currently out on maternity leave.",
        body_text="",
    )
    assert out is not None
    assert out["reply_type"] == "ooo"
    assert out["interest_level"] == "Out of office"
    assert out["apply_to_monday"] is True
