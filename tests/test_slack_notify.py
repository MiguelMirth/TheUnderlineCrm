"""Tests for Slack batch notifications (formatting + soft-fail send)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from slack_notify import (  # noqa: E402
    format_email_batch_message,
    format_monday_push_message,
    notify_email_batch,
    notify_monday_push,
    send_dm_to_lia,
    slack_notify_enabled,
)


def test_format_email_batch_first_20() -> None:
    recipients = [
        {"first_name": f"P{i}", "company_name": f"Co{i}", "email": f"p{i}@ex.com"}
        for i in range(25)
    ]
    text = format_email_batch_message(
        stage_label="Email 2 Sent",
        recipients=recipients,
        total_sent=25,
        preview_limit=20,
    )
    assert "Sent *25* emails" in text
    assert "First 20 recipients:" in text
    assert "1. P0 — Co0 (`p0@ex.com`)" in text
    assert "20. P19 — Co19" in text
    assert "P20" not in text
    assert "…and 5 more" in text


def test_format_monday_push_companies_only_unique() -> None:
    text = format_monday_push_message(
        contacts_pushed=4,
        company_names=["Fiji Water", "Budweiser", "Fiji Water", "Evian"],
    )
    assert "Pushed *4* contacts" in text
    assert "New Leads" in text
    assert "Companies added (3):" in text
    assert text.count("• Fiji Water") == 1
    assert "• Budweiser" in text
    assert "• Evian" in text
    # No person-level detail
    assert "@" not in text


def test_slack_notify_disabled_without_token(monkeypatch) -> None:
    monkeypatch.delenv("SLACK_USER_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_NOTIFY", "true")
    assert not slack_notify_enabled()
    assert send_dm_to_lia("hello") is False


def test_notify_skips_empty_batches(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-test")
    assert notify_email_batch(stage_label="Email 2 Sent", recipients=[]) is False
    assert notify_monday_push(contacts_pushed=0, company_names=[]) is False


def test_send_dm_posts_to_lia(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-test")
    monkeypatch.setenv("SLACK_LIA_USER_ID", "U_LIA")
    monkeypatch.setenv("SLACK_NOTIFY", "true")

    calls: list[tuple[str, dict]] = []

    def fake_api(method: str, *, token: str, payload: dict):
        calls.append((method, payload))
        if method == "conversations.open":
            return {"ok": True, "channel": {"id": "D123"}}
        if method == "chat.postMessage":
            return {"ok": True, "ts": "1.2"}
        raise AssertionError(method)

    monkeypatch.setattr("slack_notify._api", fake_api)
    assert send_dm_to_lia("batch done") is True
    assert calls[0][0] == "conversations.open"
    assert calls[0][1]["users"] == "U_LIA"
    assert calls[1][0] == "chat.postMessage"
    assert calls[1][1]["channel"] == "D123"
    assert calls[1][1]["text"] == "batch done"
