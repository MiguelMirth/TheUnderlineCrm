"""Tests for Cursor cloud client timeout / create handling."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from cursor_cloud_client import (  # noqa: E402
    _create_http_timeout_s,
    cursor_cloud_prompt,
)


def test_create_http_timeout_floor(monkeypatch) -> None:
    monkeypatch.delenv("CURSOR_CLOUD_CREATE_TIMEOUT", raising=False)
    assert _create_http_timeout_s(60) == 180  # floor
    assert _create_http_timeout_s(300) == 300  # tracks overall budget
    monkeypatch.setenv("CURSOR_CLOUD_CREATE_TIMEOUT", "240")
    assert _create_http_timeout_s(200) == 240  # env wins over smaller overall
    monkeypatch.setenv("CURSOR_CLOUD_CREATE_TIMEOUT", "400")
    assert _create_http_timeout_s(300) == 400


@patch("cursor_cloud_client.requests.post")
@patch("cursor_cloud_client.requests.get")
def test_create_retries_on_read_timeout_then_succeeds(mock_get, mock_post, monkeypatch) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setenv("CURSOR_CLOUD_CREATE_TIMEOUT", "180")

    ok = MagicMock()
    ok.status_code = 201
    ok.json.return_value = {
        "agent": {"id": "bc-1"},
        "run": {"id": "run-1", "status": "CREATING"},
    }
    mock_post.side_effect = [
        requests.exceptions.ReadTimeout("read timed out"),
        ok,
    ]

    poll = MagicMock()
    poll.status_code = 200
    poll.json.return_value = {"status": "FINISHED", "result": '[{"company_name":"X"}]'}
    mock_get.return_value = poll

    text = cursor_cloud_prompt("hi", name="t", archive_after=False, timeout_s=60)
    assert "company_name" in text
    assert mock_post.call_count == 2


@patch("cursor_cloud_client.requests.post")
@patch("cursor_cloud_client.requests.get")
def test_create_finished_without_result_fetches_run(mock_get, mock_post, monkeypatch) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")

    create = MagicMock()
    create.status_code = 201
    create.json.return_value = {
        "agent": {"id": "bc-2"},
        "run": {"id": "run-2", "status": "FINISHED"},  # no result in create body
    }
    mock_post.return_value = create

    poll = MagicMock()
    poll.status_code = 200
    poll.json.return_value = {"status": "FINISHED", "result": "OK"}
    mock_get.return_value = poll

    assert cursor_cloud_prompt("hi", name="t", archive_after=False) == "OK"
    mock_get.assert_called_once()
