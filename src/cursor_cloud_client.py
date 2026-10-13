"""
Cursor Cloud Agents REST API — one-shot prompts without the local SDK bridge.

The Python cursor-sdk launches a local bridge process that is unreliable on Windows
(WinError 10038). For scoring and other fire-and-forget prompts, use this module
instead: POST /v1/agents (no repo) → poll run → return assistant text.

Notes (July 2026):
  For no-repo agents, POST /v1/agents often blocks until the run finishes (~60–90s+).
  A 60s HTTP read timeout will fail right before a successful 201. Keep create
  timeout high and retry on ReadTimeout.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

from cursor_model import cloud_model_payload

_TERMINAL_RUN_STATUSES = frozenset({"FINISHED", "ERROR", "CANCELLED", "EXPIRED"})
_API_BASE = "https://api.cursor.com/v1"


def _api_key() -> str:
    key = os.getenv("CURSOR_API_KEY", "").strip()
    if not key:
        raise ValueError("CURSOR_API_KEY not set")
    return key


def _create_http_timeout_s(overall_timeout_s: int) -> int:
    """
    HTTP timeout for POST /v1/agents.

    Cursor often holds the create connection open until the no-repo run completes
    (~60–90s+ as of July 2026). Default floor is 180s; also allow up to the
    overall run budget so long extracts are not cut off mid-create.
    """
    configured = int(os.getenv("CURSOR_CLOUD_CREATE_TIMEOUT", "180"))
    return max(180, configured, min(max(overall_timeout_s, 180), 600))


def _extract_run_text(run: dict[str, Any]) -> str:
    text = (run.get("result") or "").strip()
    if text:
        return text
    # Some payloads nest assistant text under conversation / messages
    for key in ("text", "output", "response"):
        val = run.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _create_agent(
    *,
    api_key: str,
    payload: dict[str, Any],
    http_timeout_s: int,
    max_attempts: int = 3,
) -> dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            create = requests.post(
                f"{_API_BASE}/agents",
                auth=(api_key, ""),
                json=payload,
                timeout=http_timeout_s,
            )
            if create.status_code >= 400:
                raise RuntimeError(
                    f"Cursor cloud create failed ({create.status_code}): {create.text[:400]}"
                )
            return create.json()
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
            last_err = e
            print(
                f"  Cursor create timeout (attempt {attempt}/{max_attempts}, "
                f"http_timeout={http_timeout_s}s): {e}"
            )
            if attempt < max_attempts:
                time.sleep(min(5 * attempt, 15))
                continue
            raise TimeoutError(
                f"Cursor cloud create timed out after {max_attempts} attempts "
                f"(http_timeout={http_timeout_s}s). "
                f"Try raising CURSOR_CLOUD_CREATE_TIMEOUT (currently needs >60s)."
            ) from e
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < max_attempts:
                print(f"  Cursor create network error (attempt {attempt}/{max_attempts}): {e}")
                time.sleep(min(5 * attempt, 15))
                continue
            raise
    raise RuntimeError(f"Cursor cloud create failed: {last_err}")


def cursor_cloud_prompt(
    prompt: str,
    *,
    model: str | None = None,
    name: str = "underline-research",
    poll_interval_s: float = 3.0,
    timeout_s: int | None = None,
    archive_after: bool = True,
) -> str:
    """
    Run a no-repo cloud agent and return the final assistant text.
    Uses the same CURSOR_API_KEY as the SDK.
    """
    api_key = _api_key()
    timeout_s = timeout_s or int(os.getenv("CURSOR_CLOUD_TIMEOUT", "300"))
    create_timeout = _create_http_timeout_s(timeout_s)

    model_payload = cloud_model_payload()
    if model:
        model_payload = {"id": model.strip()}

    payload: dict[str, Any] = {
        "prompt": {"text": prompt},
        "model": model_payload,
        "name": name[:100],
    }

    data = _create_agent(api_key=api_key, payload=payload, http_timeout_s=create_timeout)
    agent_id = data["agent"]["id"]
    run_id = data["run"]["id"]
    # Create may already return a terminal run (common for no-repo agents).
    initial_run = data.get("run") or {}
    last_status = initial_run.get("status") or "CREATING"

    deadline = time.monotonic() + timeout_s
    try:
        if last_status in _TERMINAL_RUN_STATUSES:
            if last_status != "FINISHED":
                raise RuntimeError(f"Cursor cloud run {last_status}")
            text = _extract_run_text(initial_run)
            if text:
                return text
            # Create response often omits result — fetch the run once.

        while time.monotonic() < deadline:
            run_resp = requests.get(
                f"{_API_BASE}/agents/{agent_id}/runs/{run_id}",
                auth=(api_key, ""),
                timeout=60,
            )
            if run_resp.status_code >= 400:
                raise RuntimeError(
                    f"Cursor cloud poll failed ({run_resp.status_code}): {run_resp.text[:400]}"
                )
            run = run_resp.json()
            last_status = run.get("status") or last_status
            if last_status in _TERMINAL_RUN_STATUSES:
                if last_status != "FINISHED":
                    raise RuntimeError(f"Cursor cloud run {last_status}")
                text = _extract_run_text(run)
                if not text:
                    raise ValueError("empty Cursor cloud result")
                return text
            time.sleep(poll_interval_s)
        raise TimeoutError(f"Cursor cloud run timed out after {timeout_s}s (last={last_status})")
    finally:
        if archive_after:
            try:
                requests.post(
                    f"{_API_BASE}/agents/{agent_id}/archive",
                    auth=(api_key, ""),
                    timeout=30,
                )
            except Exception:
                pass
