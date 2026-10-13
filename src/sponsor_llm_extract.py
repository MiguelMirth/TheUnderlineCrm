"""
Extract sponsor brand names from Tavily context via Cursor Cloud (structured JSON).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, List

from cursor_cloud_client import cursor_cloud_prompt
from prospecting_qa import normalize_company_key
from sponsor_name_qa import clean_brand_name, is_benefit_phrase, is_plausible_brand_name

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]", re.MULTILINE)


def _build_prompt(event_name: str, context: dict[str, Any]) -> str:
    bundle = {
        "tavily_answer": context.get("answer") or "",
        "sources": context.get("snippets") or [],
    }
    return f"""You extract official SPONSOR and PARTNER company names for a Miami-area event.

EVENT: {event_name}

WEB RESEARCH (Tavily):
{json.dumps(bundle, ensure_ascii=False)}

Return ONLY a JSON array (no markdown). Each object:
{{
  "company_name": "Recognizable brand name",
  "sponsorship_evidence": "One factual sentence: their sponsor/partner role at this event",
  "evidence_url": "source URL from research or empty string"
}}

STRICT RULES:
- ONLY real companies/brands that officially sponsor or partner with {event_name}
- REJECT sponsor-package benefits (e.g. visibility, thought leadership, community activation, founder education)
- REJECT article/section titles (e.g. "How to Use AI in Marketing", "About Amaze:")
- REJECT the event name, venues, dates, cities, generic phrases
- company_name must be a brand marketers recognize (Neutrogena, MINI USA, Microsoft, Amaze)
- sponsorship_evidence must describe their sponsor role, not a generic page mention
- Max 12 brands; prefer consumer, CPG, beverage, lifestyle, tech with activation budgets
- Return [] if no confident sponsor brands found
"""


def _parse_json_array(text: str) -> list[Any]:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text).strip()
    m = _JSON_ARRAY_RE.search(text)
    if not m:
        raise ValueError("no JSON array in Cursor response")
    parsed = json.loads(m.group(0))
    if not isinstance(parsed, list):
        raise ValueError("expected JSON array")
    return parsed


def extract_sponsors_from_context(event_name: str, context: dict[str, Any]) -> List[dict]:
    if not os.getenv("CURSOR_API_KEY", "").strip():
        raise ValueError("CURSOR_API_KEY is required for sponsor extraction")

    if not (context.get("answer") or context.get("snippets")):
        return []

    prompt = _build_prompt(event_name, context)
    slug = re.sub(r"[^a-z0-9]+", "-", event_name.lower()).strip("-")[:40] or "event"
    text = cursor_cloud_prompt(prompt, name=f"underline-extract-{slug}")
    parsed = _parse_json_array(text)
    return _validate_rows(parsed, event_name=event_name)


def _validate_rows(rows: list[Any], *, event_name: str) -> List[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = clean_brand_name(str(row.get("company_name") or ""))
        if not name or is_benefit_phrase(name) or not is_plausible_brand_name(name, event_name=event_name):
            continue
        key = normalize_company_key(name)
        if not key or key in seen:
            continue

        evidence = str(row.get("sponsorship_evidence") or "").strip()
        if len(evidence) < 20 or is_benefit_phrase(evidence):
            continue
        if evidence.lower().startswith("mentioned on"):
            continue

        seen.add(key)
        out.append(
            {
                "company_name": name,
                "event_source": event_name,
                "sponsorship_evidence": evidence[:400],
                "evidence_url": str(row.get("evidence_url") or "").strip(),
                "discovery_source": "tavily_cursor",
            }
        )
    return out
