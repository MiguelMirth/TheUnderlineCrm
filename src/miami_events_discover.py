"""
Discover Miami / South Florida events via Tavily + Cursor for sponsor research.

One-time (or occasional) expansion of data/inputs/miami_events_seed.json.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cursor_cloud_client import cursor_cloud_prompt
from prospecting_qa import normalize_company_key
from sponsor_tavily_context import _exclude_domains, _tavily_client

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SEED = _ROOT / "data" / "inputs" / "miami_events_seed.json"

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]", re.MULTILINE)

# Broad discovery queries — Tavily credits scale with count (1 query ≈ 1–2 credits).
_DEFAULT_DISCOVERY_QUERIES = [
    "{year} Miami festivals events calendar sponsors brands",
    "{year} Miami Beach art food wine sports festivals official partners",
    "{year} South Florida Broward Palm Beach major festivals events sponsors",
    "{year} Miami music festivals concerts series sponsors partners",
    "{year} Miami tech business conferences events sponsors Florida",
    "{year} Fort Lauderdale West Palm Beach events festivals sponsors",
    "{year} Miami wellness fitness running marathon events sponsors",
    "{year} Miami boat show art week design Miami sponsors brands",
]

_JUNK_EVENT_MARKERS = (
    "webinar",
    "meetup",
    "birthday party",
    "wedding",
    "funeral",
    "orlando only",
    "tampa only",
    "jacksonville",
)


def slug_event_id(name: str) -> str:
    """Stable id from event name: 'Art Basel Miami Beach' → art_basel_miami_beach."""
    key = normalize_company_key(name)
    slug = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    return slug[:60] or "event"


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


def _event_name_key(name: str) -> str:
    return normalize_company_key(name)


def _is_plausible_event(name: str, *, year: int) -> bool:
    n = (name or "").strip()
    if len(n) < 4 or len(n) > 120:
        return False
    low = n.lower()
    if any(m in low for m in _JUNK_EVENT_MARKERS):
        return False
    # Prefer Miami / South FL signal or well-known anchor events
    geo = (
        "miami",
        "south beach",
        "wynwood",
        "brickell",
        "coral gables",
        "fort lauderdale",
        "broward",
        "palm beach",
        "south florida",
        "dade",
        "homestead",
        "key biscayne",
    )
    if any(g in low for g in geo):
        return True
    # F1, Art Basel, etc. may omit city in short name
    return len(n.split()) >= 2


def _normalize_event_row(row: dict[str, Any], *, year: int) -> dict[str, Any] | None:
    name = (row.get("name") or row.get("event_name") or "").strip()
    if not name or not _is_plausible_event(name, year=year):
        return None

    event_id = (row.get("event_id") or "").strip() or slug_event_id(name)
    event_id = re.sub(r"[^a-z0-9_]+", "_", event_id.lower()).strip("_")[:60]

    queries = row.get("search_queries") or []
    if isinstance(queries, str):
        queries = [queries]
    queries = [str(q).strip() for q in queries if str(q).strip()]

    if not queries:
        queries = [
            f"{name} {year} official sponsors partners brands",
            f"{name} Miami Florida sponsor list",
        ]
    else:
        # Ensure year + sponsor intent in queries
        fixed: list[str] = []
        for q in queries[:3]:
            q_low = q.lower()
            if str(year) not in q:
                q = f"{q} {year}"
            if "sponsor" not in q_low and "partner" not in q_low:
                q = f"{q} sponsors partners"
            fixed.append(q)
        queries = fixed

    out: dict[str, Any] = {
        "event_id": event_id,
        "name": name,
        "search_queries": queries[:3],
    }
    month = (row.get("month") or "").strip()
    if month:
        out["month"] = month[:20]
    city = (row.get("city") or row.get("region") or "").strip()
    if city:
        out["region"] = city[:40]
    return out


def merge_event_seeds(existing: list[dict], discovered: list[dict]) -> tuple[list[dict], int]:
    """
    Merge discovered events into existing seed. Existing rows win on name collision.
    Returns (merged_list, new_count).
    """
    merged: list[dict] = [dict(e) for e in existing if isinstance(e, dict)]
    seen_ids = {(e.get("event_id") or "").strip().lower() for e in merged}
    seen_names = {_event_name_key(e.get("name") or "") for e in merged if e.get("name")}

    new_count = 0
    for row in discovered:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or "").strip()
        if not name:
            continue
        nk = _event_name_key(name)
        if nk in seen_names:
            continue
        eid = (row.get("event_id") or "").strip().lower()
        if eid and eid in seen_ids:
            continue
        merged.append(row)
        seen_names.add(nk)
        if eid:
            seen_ids.add(eid)
        new_count += 1

    merged.sort(key=lambda e: (e.get("name") or "").lower())
    return merged, new_count


def _snippet_is_event_relevant(row: dict, *, year: int, region: str) -> bool:
    title = (row.get("title") or "").lower()
    content = (row.get("content") or "").lower()
    url = (row.get("url") or "").lower()
    blob = f"{title} {content} {url}"

    event_markers = (
        "festival",
        "event",
        "conference",
        "week",
        "expo",
        "fair",
        "show",
        "open",
        "grand prix",
        "marathon",
        "parade",
        "concert",
        "calendar",
        "schedule",
    )
    if not any(m in blob for m in event_markers):
        return False

    geo = (
        "miami",
        "south florida",
        "miami beach",
        "fort lauderdale",
        "broward",
        "palm beach",
        "wynwood",
        "brickell",
        "homestead",
        "coral gables",
    )
    if region.lower() in ("south florida", "south fl"):
        if not any(g in blob for g in geo):
            return False
    elif region.lower() in ("miami", "miami-dade"):
        if "miami" not in blob and "south florida" not in blob:
            return False

    if str(year) in blob or f"{year - 1}" in blob or f"{year + 1}" in blob:
        return True
    return any(g in blob for g in geo)


def gather_miami_events_research(
    *,
    year: int = 2026,
    region: str = "South Florida",
    extra_queries: list[str] | None = None,
) -> dict[str, Any]:
    """Run Tavily discovery searches; return aggregated answer + snippets."""
    client = _tavily_client()
    depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip()
    answer_mode = os.getenv("TAVILY_INCLUDE_ANSWER", "advanced").strip()
    max_results = int(os.getenv("TAVILY_MAX_RESULTS", "10"))
    max_queries = int(os.getenv("MIAMI_EVENTS_TAVILY_QUERIES", "8"))

    templates = list(_DEFAULT_DISCOVERY_QUERIES)
    if extra_queries:
        templates.extend(extra_queries)

    answers: list[str] = []
    snippets: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    queries_run: list[str] = []

    for tmpl in templates[:max_queries]:
        query = tmpl.format(year=year, region=region)
        queries_run.append(query)
        resp = client.search(
            query=query,
            search_depth=depth,
            max_results=max_results,
            include_answer=answer_mode,
            exclude_domains=_exclude_domains(),
        )
        ans = (resp.get("answer") or "").strip()
        if ans:
            answers.append(f"[Query: {query}]\n{ans}")

        for row in resp.get("results") or []:
            url = (row.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            if not _snippet_is_event_relevant(row, year=year, region=region):
                continue
            seen_urls.add(url)
            snippets.append(
                {
                    "title": (row.get("title") or "").strip()[:200],
                    "content": (row.get("content") or "").strip()[:600],
                    "url": url,
                }
            )

    return {
        "year": year,
        "region": region,
        "queries_run": queries_run,
        "answer": "\n\n".join(answers),
        "snippets": snippets[:40],
    }


def extract_events_from_research(
    context: dict[str, Any],
    *,
    year: int,
    region: str,
    existing_names: list[str] | None = None,
) -> list[dict]:
    """Cursor: Tavily bundle → structured event seed rows."""
    if not os.getenv("CURSOR_API_KEY", "").strip():
        raise ValueError("CURSOR_API_KEY is required")

    existing = existing_names or []
    existing_block = "\n".join(f"- {n}" for n in existing[:80]) or "(none)"

    bundle = {
        "year": year,
        "region": region,
        "tavily_answers": context.get("answer") or "",
        "sources": context.get("snippets") or [],
    }

    prompt = f"""You build a research list of major {region} events in {year} for B2B **sponsorship** prospecting.

We already track these events (do NOT duplicate — use a distinct name if it's the same event):
{existing_block}

WEB RESEARCH (Tavily):
{json.dumps(bundle, ensure_ascii=False)}

Return ONLY a JSON array (no markdown). Each object:
{{
  "event_id": "snake_case_slug",
  "name": "Official event name",
  "search_queries": [
    "Event Name {year} official sponsors partners brands",
    "Event Name Miami sponsor list"
  ],
  "month": "optional e.g. March",
  "city": "optional e.g. Miami Beach"
}}

RULES:
- Real festivals, sports, art, food/wine, music, tech, wellness, boat/auto shows in Miami-Dade, Broward, or Palm Beach
- Events brands sponsor (CPG, beverage, lifestyle, tech activations) — not tiny meetups or private parties
- REJECT Orlando/Tampa/Jacksonville-only events unless they are clearly Miami/South FL editions
- REJECT generic phrases ("things to do", "best events") — must be named events
- search_queries: 2 strings optimized to find **sponsor/partner** pages for Apollo/Tavily later
- Include marquee events even if already listed ONLY if you have a materially better official name (rare)
- Target 25–60 **new** distinct events from research; return [] if nothing confident
"""

    text = cursor_cloud_prompt(prompt, name="underline-miami-events-discover", timeout_s=360)
    parsed = _parse_json_array(text)

    out: list[dict] = []
    seen: set[str] = set()
    for row in parsed:
        if not isinstance(row, dict):
            continue
        norm = _normalize_event_row(row, year=year)
        if not norm:
            continue
        nk = _event_name_key(norm["name"])
        if nk in seen:
            continue
        seen.add(nk)
        out.append(norm)
    return out


def load_seed(path: Path | str | None = None) -> list[dict]:
    p = Path(path) if path else _DEFAULT_SEED
    if not p.is_file():
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_miami_events_seed(
    events: list[dict],
    path: Path | str | None = None,
    *,
    backup: bool = True,
) -> str:
    p = Path(path) if path else _DEFAULT_SEED
    p.parent.mkdir(parents=True, exist_ok=True)

    if backup and p.is_file():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
        bak = p.with_name(f"{p.stem}.backup_{ts}{p.suffix}")
        bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Backup → {bak}")

    with open(p, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return str(p)
