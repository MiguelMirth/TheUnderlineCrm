"""
Gemini structured QA for Concert and Venue.

The payload is brand, industry, title, person state, and an evidence snippet.
Names and emails are not sent. A transport error or unparseable reply becomes
verdict "flag" with reason "LLM unavailable". It never becomes "pass".
"""
from __future__ import annotations

import os
from typing import Any

import requests

from engine.spend import Meter

PROMPT_VERSION = "1"
GEMINI_MODEL_DEFAULT = "gemini-3.8-flash"
_REASON_MAX = 140

_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "rows": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "row_id": {"type": "STRING"},
                    "verdict": {"type": "STRING", "enum": ["pass", "flag", "fail"]},
                    "reason": {"type": "STRING"},
                    "region": {"type": "STRING"},
                    "sector": {"type": "STRING"},
                    "sponsorship_evidence": {"type": "STRING", "enum": ["yes", "no", "unclear"]},
                },
                "required": ["row_id", "verdict", "reason", "region", "sector", "sponsorship_evidence"],
            },
        }
    },
    "required": ["rows"],
}


def gemini_model() -> str:
    return os.getenv("GEMINI_QA_MODEL", GEMINI_MODEL_DEFAULT).strip() or GEMINI_MODEL_DEFAULT


def gemini_batch_size() -> int:
    raw = os.getenv("GEMINI_QA_BATCH_SIZE", "20").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 20


def gemini_block_reason() -> str | None:
    """Why Gemini cannot be called. A missing ceiling does not block it."""
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return "GEMINI_API_KEY is not set"
    return None


def qa_input(lead: dict[str, Any]) -> dict[str, str]:
    """Fields the model is allowed to see. No person name and no email."""
    person = lead.get("person") or {}
    org = person.get("organization") or {}
    evidence = " ".join(str(item) for item in (lead.get("evidence") or []) if item)[:400]
    return {
        "row_id": str(lead.get("id") or ""),
        "brand": str(lead.get("shelf_brand") or org.get("name") or ""),
        "industry": str(org.get("industry") or ""),
        "title": str(lead.get("title") or ""),
        "person_state": str(person.get("state") or ""),
        "evidence": evidence,
    }


def gemini_cache_key(vertical_id: str, fields: dict[str, str]) -> str:
    from engine.spend import cache_digest

    canonical = {key: fields.get(key, "") for key in ("brand", "industry", "title", "person_state", "evidence")}
    return f"{vertical_id}:{cache_digest(canonical)}:{PROMPT_VERSION}"


def _unavailable(row_id: str) -> dict[str, str]:
    return {
        "row_id": row_id,
        "verdict": "flag",
        "reason": "LLM unavailable",
        "region": "",
        "sector": "",
        "sponsorship_evidence": "unclear",
    }


def _clip(value: Any) -> str:
    return str(value or "").strip()[:_REASON_MAX]


def normalize_verdict(raw: Any, row_id: str) -> dict[str, str]:
    """Coerce one model row. Anything that is not pass, flag, or fail becomes flag."""
    if not isinstance(raw, dict):
        return _unavailable(row_id)
    verdict = str(raw.get("verdict") or "").strip().lower()
    if verdict not in ("pass", "flag", "fail"):
        return _unavailable(row_id)
    evidence = str(raw.get("sponsorship_evidence") or "unclear").strip().lower()
    if evidence not in ("yes", "no", "unclear"):
        evidence = "unclear"
    return {
        "row_id": row_id,
        "verdict": verdict,
        "reason": _clip(raw.get("reason")),
        "region": _clip(raw.get("region")),
        "sector": _clip(raw.get("sector")),
        "sponsorship_evidence": evidence,
    }


def _prompt(vertical_id: str, rows: list[dict[str, str]]) -> str:
    if vertical_id == "venue_rental":
        ask = (
            "Decide whether each person is someone who plans or books events, weddings, or venue rentals. "
            "Fail recruiters and unrelated sales roles. Pass event planners, producers, and hospitality bookers."
        )
    else:
        ask = (
            "Decide whether each person is a paid sponsorship or brand buyer who could sponsor a concert series. "
            "Pass official, title, or presenting sponsorship buyers. Fail community, collab, in-kind, and nonprofit desks."
        )
    lines = [ask, "Use only the fields given. Reply with the schema.", ""]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    f"row_id={row['row_id']}",
                    f"brand={row['brand']}",
                    f"industry={row['industry']}",
                    f"title={row['title']}",
                    f"person_state={row['person_state']}",
                    f"evidence={row['evidence']}",
                ]
            )
        )
    return "\n".join(lines)


def _text_from_response(data: dict[str, Any]) -> str:
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    usable = [
        part.get("text")
        for part in parts
        if isinstance(part, dict) and part.get("text") and not part.get("thought")
    ]
    if not usable:
        usable = [part.get("text") for part in parts if isinstance(part, dict) and part.get("text")]
    return "\n".join(usable).strip()


def _generate_once(model: str, vertical_id: str, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    import json

    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    response = requests.post(
        url,
        params={"key": key},
        json={
            "contents": [{"parts": [{"text": _prompt(vertical_id, rows)}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": _SCHEMA,
                "thinkingConfig": {"thinkingLevel": "LOW"},
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    parsed = json.loads(_text_from_response(response.json()) or "{}")
    raw_rows = parsed.get("rows") if isinstance(parsed, dict) else parsed
    if not isinstance(raw_rows, list):
        raise ValueError("Gemini did not return rows")
    by_id = {str(item.get("row_id")): item for item in raw_rows if isinstance(item, dict)}
    return [normalize_verdict(by_id.get(row["row_id"]), row["row_id"]) for row in rows]


def generate_batch(vertical_id: str, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """One Gemini request. Retries a busy model, then tries the fallback model. Tests replace this."""
    import time

    models = [gemini_model()]
    fallback = os.getenv("GEMINI_QA_FALLBACK_MODEL", "gemini-2.5-flash").strip()
    if fallback and fallback not in models:
        models.append(fallback)
    last_error: Exception | None = None
    for model in models:
        for attempt in range(3):
            try:
                return _generate_once(model, vertical_id, rows)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                last_error = exc
                if status in (429, 500, 503) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            except (ValueError, requests.RequestException) as exc:
                last_error = exc
                break
    if last_error is None:
        raise RuntimeError("Gemini did not return a verdict")
    raise last_error


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def apply_gemini(store: Any, run: dict[str, Any], leads: list[dict[str, Any]], *, pass_state: str) -> str:
    """
    Write an LLM verdict onto each lead. pass and flag take pass_state. fail becomes llm_failed.
    A failed call becomes llm_failed with reason "LLM unavailable". It is not cached and not charged.
    """
    from engine.spend import BudgetStop

    if not leads:
        return "no rows for Gemini"
    vertical_id = run["vertical_id"]
    meter = Meter(store, run["id"], "llm")
    pending: list[dict[str, Any]] = []
    for lead in leads:
        fields = qa_input(lead)
        key = gemini_cache_key(vertical_id, fields)
        cached = meter.gemini_hit(key)
        if isinstance(cached, dict) and cached.get("reason") != "LLM unavailable":
            _write(store, lead, normalize_verdict(cached, lead["id"]), pass_state)
            continue
        pending.append(lead)

    flagged = 0
    for batch in _chunks(pending, gemini_batch_size()):
        rows = [qa_input(lead) for lead in batch]
        try:
            meter._can_charge("gemini", 1)
            verdicts = generate_batch(vertical_id, rows)
            meter.charge_gemini()
        except BudgetStop:
            raise
        except Exception:
            verdicts = [_unavailable(row["row_id"]) for row in rows]
            flagged += len(batch)
        by_id = {item["row_id"]: item for item in verdicts}
        for lead in batch:
            fields = qa_input(lead)
            verdict = normalize_verdict(by_id.get(lead["id"]), lead["id"])
            if verdict["reason"] != "LLM unavailable":
                meter.remember_gemini(gemini_cache_key(vertical_id, fields), verdict)
            _write(store, lead, verdict, pass_state)
    return f"Gemini judged {len(leads)} row(s)" + (f", {flagged} unavailable" if flagged else "")


def _write(store: Any, lead: dict[str, Any], verdict: dict[str, str], pass_state: str) -> None:
    if verdict["verdict"] == "fail" or verdict["reason"] == "LLM unavailable":
        state = "llm_failed"
    else:
        state = pass_state
    store.update_lead(lead["id"], state=state, llm=verdict)
