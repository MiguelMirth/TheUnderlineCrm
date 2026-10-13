import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from reply_triage_gemini import polish_notes_summary  # noqa: E402


def test_polish_replaces_raw_paste() -> None:
    raw = (
        "[Reply triage 2026-05-20] type=wrong_person\n"
        "Thank you for your message. Please note that Trisha is no longer with Docker."
    )
    out = polish_notes_summary(
        raw,
        reply_type="wrong_person",
        from_name="Trisha McCanna",
        blob="Please contact terri.avnaim@docker.com",
    )
    assert "Reply triage" not in out
    assert "Thank you for your message" not in out
    assert len(out) < 200
