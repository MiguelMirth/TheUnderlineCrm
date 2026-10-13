"""
Tavily paid-sponsorship evidence for Concert Series brands.

Apollo cannot filter "has paid sponsorship history". We batch several brands into
one Tavily search (1 credit / search on fast|basic) and run a few of those
searches concurrently. Results are cached for the run and on disk so the same
company is never billed twice.

Does not run Cursor scoring — that stays on the sponsor-research path.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from concert_series_config import (
    concert_spend_batch_size,
    concert_spend_cache_path,
    concert_spend_concurrency,
    concert_spend_tavily_depth,
)
from prospecting_qa import normalize_company_key
from sponsor_tavily_context import _exclude_domains

SPEND_PASS = "pass"
SPEND_FAIL = "fail"
SPEND_AMBIGUOUS = "ambiguous"
SPEND_SKIPPED = "skipped"

CACHE_VERSION = 2

_PASS_PHRASES = (
    "official sponsor",
    "title sponsor",
    "presenting sponsor",
    "festival sponsor",
    "concert sponsor",
    "series sponsor",
    "pouring rights",
    "pouring-rights",
    "paid activation",
    "official presenting",
)

_FAIL_PHRASES = (
    "in-kind",
    "in kind",
    "media partner",
    "community partner",
    "collaborative partner",
    "collaborative",
    "nonprofit partner",
    "non-profit partner",
    "non profit partner",
    "proud partner",
)

_NOTES_MAX = 240


@dataclass
class SpendEvidence:
    verdict: str
    reason: str
    notes: str = ""
    query: str = ""
    cached: bool = False

    def as_audit(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "notes": self.notes,
            "cached": self.cached,
        }

    def to_disk(self) -> Dict[str, str]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "notes": self.notes,
            "query": self.query,
        }


def company_spend_key(org_name: str) -> str:
    return normalize_company_key(org_name) or (org_name or "").strip().lower()


def spend_search_query(brand: str) -> str:
    """Single-brand query (tests + leftover 1-brand batches)."""
    return spend_search_query_batch([brand])


def spend_search_query_batch(brands: List[str]) -> str:
    """
    Natural-language multi-brand query. Boolean OR + quoted phrases was
    returning empty Tavily snippets (1 credit, zero signal).
    """
    names = [f'"{(b or "").strip()}"' for b in brands if (b or "").strip()]
    joined = ", ".join(names) or '""'
    return (
        "official sponsor OR title sponsor OR presenting sponsor "
        f"of a festival, concert, or sports series: {joined}"
    )


def classify_spend_text(blob: str) -> Tuple[str, str]:
    """
    Heuristic on concatenated Tavily snippets for ONE brand.
    Pass language wins over fail language. Neither → ambiguous (fail closed).
    """
    text = (blob or "").strip().lower()
    if not text:
        return SPEND_AMBIGUOUS, "no_snippets"

    has_pass = any(p in text for p in _PASS_PHRASES)
    has_fail = any(p in text for p in _FAIL_PHRASES)

    if has_pass:
        hit = next(p for p in _PASS_PHRASES if p in text)
        return SPEND_PASS, f"paid_phrase:{hit}"
    if has_fail:
        hit = next(p for p in _FAIL_PHRASES if p in text)
        return SPEND_FAIL, f"collab_phrase:{hit}"
    return SPEND_AMBIGUOUS, "no_paid_or_collab_phrase"


def brand_mentioned(org_name: str, text: str) -> bool:
    t = (text or "").lower()
    key = company_spend_key(org_name)
    if not key:
        return False
    if len(key) <= 4:
        return re.search(rf"\b{re.escape(key)}\b", t) is not None
    if key in t:
        return True
    tokens = [x for x in key.split() if len(x) >= 4]
    if not tokens:
        return re.search(rf"\b{re.escape(key)}\b", t) is not None
    return all(tok in t for tok in tokens)


def _host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").removeprefix("www.")
    except Exception:
        return ""


def _flatten_tavily(resp: Dict[str, Any]) -> Tuple[str, List[Dict[str, str]]]:
    parts: List[str] = []
    answer = (resp.get("answer") or "").strip()
    if answer:
        parts.append(answer)
    snippets: List[Dict[str, str]] = []
    for row in resp.get("results") or []:
        title = (row.get("title") or "").strip()
        content = (row.get("content") or "").strip()
        url = (row.get("url") or "").strip()
        snippets.append({"title": title, "content": content, "url": url})
        if title:
            parts.append(title)
        if content:
            parts.append(content)
    return "\n".join(parts), snippets


def _slice_for_brand(
    org_name: str,
    snippets: List[Dict[str, str]],
    answer: str = "",
) -> Tuple[str, List[Dict[str, str]]]:
    """Keep only snippets/answer lines that mention this brand — no cross-brand leak."""
    matched: List[Dict[str, str]] = []
    parts: List[str] = []
    if answer and brand_mentioned(org_name, answer):
        for line in answer.splitlines():
            if brand_mentioned(org_name, line):
                parts.append(line)
        if not parts:
            parts.append(answer)
    for row in snippets:
        blob = f"{row.get('title', '')} {row.get('content', '')}"
        if brand_mentioned(org_name, blob):
            matched.append(row)
            parts.append(blob)
    return "\n".join(parts), matched


def _notes_sentence(brand: str, snippets: List[Dict[str, str]], verdict: str) -> str:
    if verdict != SPEND_PASS:
        return ""
    name = (brand or "").strip() or "Brand"
    for row in snippets:
        blob = f"{row.get('title', '')} {row.get('content', '')}".lower()
        if not any(p in blob for p in _PASS_PHRASES):
            continue
        host = _host(row.get("url") or "")
        title = (row.get("title") or "").strip()
        bit = title[:120] if title else "official sponsor"
        suffix = f" ({host})" if host else ""
        return f"{name} — {bit}{suffix}"[:_NOTES_MAX]
    return f"{name} — documented paid sponsorship"[:_NOTES_MAX]


def _usage_credits(resp: Dict[str, Any]) -> float:
    usage = resp.get("usage") if isinstance(resp, dict) else None
    if isinstance(usage, dict):
        for key in ("credits", "total_credits", "credits_used"):
            raw = usage.get(key)
            if raw is None:
                continue
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
    return 1.0


def _chunk(items: List[str], size: int) -> List[List[str]]:
    if size <= 0:
        return [items] if items else []
    return [items[i : i + size] for i in range(0, len(items), size)]


def _search_kwargs() -> Dict[str, Any]:
    return {
        "search_depth": concert_spend_tavily_depth(),
        "max_results": int(os.getenv("CONCERT_SPEND_TAVILY_MAX_RESULTS", "8")),
        "include_answer": False,
        "include_usage": True,
        "exclude_domains": _exclude_domains(),
        "timeout": 10,
    }


def tavily_search(query: str) -> Dict[str, Any]:
    """Sync Tavily search — mock this in tests."""
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("tavily_key_missing")
    from tavily import TavilyClient

    client = TavilyClient(api_key=api_key)
    return client.search(query=query, **_search_kwargs()) or {}


async def _tavily_search_async(query: str, client) -> Dict[str, Any]:
    return await client.search(query=query, **_search_kwargs()) or {}


def evidence_from_tavily_response(
    brands: List[str],
    resp: Dict[str, Any],
    query: str,
) -> Dict[str, SpendEvidence]:
    _blob, snippets = _flatten_tavily(resp)
    answer = (resp.get("answer") or "").strip()
    out: Dict[str, SpendEvidence] = {}
    for name in brands:
        brand_blob, brand_snips = _slice_for_brand(name, snippets, answer)
        verdict, reason = classify_spend_text(brand_blob)
        out[company_spend_key(name)] = SpendEvidence(
            verdict=verdict,
            reason=reason,
            notes=_notes_sentence(name, brand_snips, verdict),
            query=query,
        )
    return out


def search_brand_chunk(brands: List[str]) -> Tuple[Dict[str, SpendEvidence], float]:
    """One Tavily request covering several brands. Returns (by_key, credits)."""
    names = [(b or "").strip() for b in brands if (b or "").strip()]
    if not names:
        return {}, 0.0
    query = spend_search_query_batch(names)
    try:
        resp = tavily_search(query)
    except RuntimeError as e:
        if str(e) == "tavily_key_missing":
            skipped = {
                company_spend_key(n): SpendEvidence(
                    verdict=SPEND_SKIPPED, reason="tavily_key_missing", query=query
                )
                for n in names
            }
            return skipped, 0.0
        raise
    except Exception as e:  # noqa: BLE001 — fail closed
        amb = {
            company_spend_key(n): SpendEvidence(
                verdict=SPEND_AMBIGUOUS, reason=f"tavily_error:{e}", query=query
            )
            for n in names
        }
        return amb, 0.0
    return evidence_from_tavily_response(names, resp, query), _usage_credits(resp)


async def _search_brand_chunk_async(brands: List[str], client) -> Tuple[Dict[str, SpendEvidence], float]:
    names = [(b or "").strip() for b in brands if (b or "").strip()]
    if not names:
        return {}, 0.0
    query = spend_search_query_batch(names)
    try:
        resp = await _tavily_search_async(query, client)
    except Exception as e:  # noqa: BLE001
        amb = {
            company_spend_key(n): SpendEvidence(
                verdict=SPEND_AMBIGUOUS, reason=f"tavily_error:{e}", query=query
            )
            for n in names
        }
        return amb, 0.0
    return evidence_from_tavily_response(names, resp or {}, query), _usage_credits(resp or {})


async def _search_chunks_async(
    chunks: List[List[str]],
    *,
    concurrency: int,
) -> Tuple[Dict[str, SpendEvidence], float]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        query = spend_search_query_batch([n for c in chunks for n in c])
        skipped = {
            company_spend_key(n): SpendEvidence(
                verdict=SPEND_SKIPPED, reason="tavily_key_missing", query=query
            )
            for c in chunks
            for n in c
        }
        return skipped, 0.0

    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=api_key)
    sem = asyncio.Semaphore(max(1, concurrency))
    merged: Dict[str, SpendEvidence] = {}
    credits = 0.0

    async def _one(chunk: List[str]) -> Tuple[Dict[str, SpendEvidence], float]:
        async with sem:
            return await _search_brand_chunk_async(chunk, client)

    results = await asyncio.gather(*[_one(c) for c in chunks], return_exceptions=True)
    for item in results:
        if isinstance(item, Exception):
            continue
        ev_map, used = item
        merged.update(ev_map)
        credits += used
    return merged, credits


def search_brand_chunks(
    chunks: List[List[str]],
    *,
    concurrency: int = 3,
) -> Tuple[Dict[str, SpendEvidence], float]:
    """Run one or more multi-brand Tavily searches. Concurrent when chunks > 1."""
    if not chunks:
        return {}, 0.0
    if len(chunks) == 1 or concurrency <= 1:
        merged: Dict[str, SpendEvidence] = {}
        credits = 0.0
        for chunk in chunks:
            ev_map, used = search_brand_chunk(chunk)
            merged.update(ev_map)
            credits += used
        return merged, credits
    return asyncio.run(_search_chunks_async(chunks, concurrency=concurrency))


class ConcertSpendCache:
    """Memory + disk cache. ensure_many() is 1 Tavily credit per 8 brands (default)."""

    def __init__(self, *, enabled: bool = True, cache_path: Optional[str] = None) -> None:
        self.enabled = enabled
        self.cache_path = cache_path if cache_path is not None else concert_spend_cache_path()
        self._by_company: Dict[str, SpendEvidence] = {}
        self.stats: Dict[str, float] = {
            SPEND_PASS: 0,
            SPEND_FAIL: 0,
            SPEND_AMBIGUOUS: 0,
            SPEND_SKIPPED: 0,
            "tavily_calls": 0,
            "tavily_credits": 0.0,
            "brands_looked_up": 0,
            "disk_hits": 0,
        }
        self._load_disk()

    def has(self, org_name: str) -> bool:
        key = company_spend_key(org_name)
        return bool(key) and key in self._by_company

    def _load_disk(self) -> None:
        path = self.cache_path
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict) or int(raw.get("_version") or 0) != CACHE_VERSION:
            return
        entries = raw.get("entries") or {}
        if not isinstance(entries, dict):
            return
        for key, row in entries.items():
            if not key or not isinstance(row, dict):
                continue
            self._by_company[str(key)] = SpendEvidence(
                verdict=str(row.get("verdict") or SPEND_AMBIGUOUS),
                reason=str(row.get("reason") or "disk_cache"),
                notes=str(row.get("notes") or ""),
                query=str(row.get("query") or ""),
                cached=True,
            )

    def _save_disk(self) -> None:
        path = self.cache_path
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            payload = {
                "_version": CACHE_VERSION,
                "entries": {k: v.to_disk() for k, v in self._by_company.items()},
            }
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, path)
        except OSError:
            return

    def _remember(self, key: str, ev: SpendEvidence, *, from_disk: bool = False) -> None:
        self._by_company[key] = ev
        if from_disk:
            return
        self.stats[ev.verdict] = self.stats.get(ev.verdict, 0) + 1

    def ensure_many(self, org_names: Iterable[str]) -> None:
        if not self.enabled:
            return
        needed: List[str] = []
        seen: set[str] = set()
        for name in org_names:
            key = company_spend_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            if key in self._by_company:
                if self._by_company[key].cached:
                    self.stats["disk_hits"] = self.stats.get("disk_hits", 0) + 1
                continue
            needed.append(name)
        if not needed:
            return

        batch = concert_spend_batch_size()
        concurrency = concert_spend_concurrency()
        chunks = _chunk(needed, batch)
        ev_map, credits = search_brand_chunks(chunks, concurrency=concurrency)
        self.stats["tavily_calls"] = self.stats.get("tavily_calls", 0) + len(chunks)
        self.stats["tavily_credits"] = self.stats.get("tavily_credits", 0) + credits
        self.stats["brands_looked_up"] = self.stats.get("brands_looked_up", 0) + len(needed)
        for name in needed:
            key = company_spend_key(name)
            ev = ev_map.get(key)
            if ev is None:
                ev = SpendEvidence(verdict=SPEND_AMBIGUOUS, reason="batch_miss")
            self._remember(key, ev)
        self._save_disk()

    def evaluate(self, org_name: str, website: str = "") -> SpendEvidence:
        del website
        if not self.enabled:
            return SpendEvidence(verdict=SPEND_SKIPPED, reason="spend_evidence_disabled")

        key = company_spend_key(org_name)
        if not key:
            return SpendEvidence(verdict=SPEND_AMBIGUOUS, reason="empty_company")

        cached = self._by_company.get(key)
        if cached is not None:
            return SpendEvidence(
                verdict=cached.verdict,
                reason=cached.reason,
                notes=cached.notes,
                query=cached.query,
                cached=True,
            )

        self.ensure_many([org_name])
        stored = self._by_company.get(key)
        if stored is None:
            return SpendEvidence(verdict=SPEND_AMBIGUOUS, reason="empty_company")
        return stored
