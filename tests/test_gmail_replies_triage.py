import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from gmail_replies import (  # noqa: E402
    MAX_MIME_DEPTH,
    InboundReplyMessage,
    extract_plain_body,
    filter_skip_senders,
    gmail_query_for_month,
    iter_mime_parts,
    month_date_range,
    parse_from_header,
    parse_skip_senders,
)
from reply_triage_gemini import INTEREST_OUT_OF_OFFICE, normalize_triage  # noqa: E402
from reply_triage_monday import group_id_for_hint, triage_to_column_values  # noqa: E402


def test_month_date_range() -> None:
    start, end = month_date_range(2026, 5)
    assert start.isoformat() == "2026-05-01"
    assert end.isoformat() == "2026-06-01"
    start2, end2 = month_date_range(2025, 12)
    assert start2.isoformat() == "2025-12-01"
    assert end2.isoformat() == "2026-01-01"


def test_gmail_query_for_month() -> None:
    q = gmail_query_for_month(2026, 5, label="REPLIES")
    assert "label:REPLIES" in q
    assert "after:2026/05/01" in q
    assert "before:2026/06/01" in q
    assert "-from:me" in q


def test_skip_lia_sender() -> None:
    skip = parse_skip_senders("")
    msgs = [
        InboundReplyMessage("1", "t", "lia@knowyourmirth.com", "Lia", "s", "2026-05-01", "", ""),
        InboundReplyMessage("2", "t", "prospect@brand.com", "P", "s", "2026-05-01", "", ""),
    ]
    kept, n = filter_skip_senders(msgs, skip)
    assert n == 1
    assert len(kept) == 1
    assert kept[0].from_email == "prospect@brand.com"


def test_parse_from_header() -> None:
    name, addr = parse_from_header("Jane Doe <jane@acme.com>")
    assert name == "Jane Doe"
    assert addr == "jane@acme.com"


def test_normalize_triage_spam() -> None:
    out = normalize_triage(
        {
            "reply_type": "spam",
            "lead_status": "Replied",
            "apply_to_monday": True,
            "confidence": "high",
        }
    )
    assert out["reply_type"] == "spam"
    assert out["apply_to_monday"] is False


def test_normalize_triage_ooo_interest() -> None:
    out = normalize_triage(
        {
            "reply_type": "ooo",
            "lead_status": "Replied",
            "confidence": "medium",
        }
    )
    assert out["interest_level"] == "Out of office"
    assert out["apply_to_monday"] is True


def test_triage_to_column_values() -> None:
    cols = triage_to_column_values(
        {
            "lead_status": "Replied",
            "interest_level": "High",
            "next_action_date": "2026-05-25",
            "notes_summary": "Interested in a 15-minute call next week.",
            "next_action": "Schedule call",
        },
        received_at="2026-05-19",
        reply_type="positive_curious",
    )
    assert cols["status"] == {"label": "Replied"}
    assert cols["color_mm0xtvq2"] == {"label": "High"}
    assert "2026-05-19" in cols["date_mm0xerpc"]["date"]
    assert cols["text_mm0xz0w2"] == "Interested in a 15-minute call next week."
    assert "Reply triage" not in cols["text_mm0xz0w2"]
    assert "Next:" not in cols["text_mm0xz0w2"]


def test_group_id_for_hint() -> None:
    assert group_id_for_hint("engaged") == "group_mm0xj5rd"
    assert group_id_for_hint("none") == ""


def _nested_part(depth: int, mime: str = "multipart/mixed") -> dict:
    if depth <= 0:
        return {
            "mimeType": "text/plain",
            "body": {"data": "aGVsbG8="},  # "hello" in base64
        }
    return {"mimeType": mime, "parts": [_nested_part(depth - 1)]}


def test_iter_mime_parts_deep_tree() -> None:
    root = _nested_part(80)
    parts = iter_mime_parts(root, max_depth=MAX_MIME_DEPTH)
    assert len(parts) >= 1
    assert len(parts) <= 80


def test_extract_plain_body_deep_tree() -> None:
    text = extract_plain_body(_nested_part(40))
    assert "hello" in text


def test_extract_plain_body_absurd_depth_no_recursion() -> None:
    """Pathological nesting must not RecursionError (may miss leaf past max_depth)."""
    text = extract_plain_body(_nested_part(500))
    assert isinstance(text, str)
