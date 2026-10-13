"""
Tavily retrieval for event sponsor research — search + advanced answer, no page scraping.

Tavily docs recommend: search for URLs/snippets, use include_answer for synthesis,
and avoid regex on raw page extract. We gather snippets + answer for LLM extraction.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

_DEFAULT_EXCLUDE = (
    "cited.md",
    "medium.com",
    "linkedin.com",
    "pinterest.com",
    "reddit.com",
    "quora.com",
    "wikipedia.org",
    "techweekgr.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
)

_SPONSOR_KEYWORDS = ("sponsor", "partner", "presenting", "powered by", "official", "supported by")


def _tavily_client():
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TAVILY_API_KEY is not set")
    from tavily import TavilyClient

    return TavilyClient(api_key=api_key)


def _exclude_domains() -> list[str]:
    extra = os.getenv("TAVILY_EXCLUDE_DOMAINS", "").strip()
    domains = list(_DEFAULT_EXCLUDE)
    if extra:
        domains.extend(d.strip() for d in extra.split(",") if d.strip())
    return domains


def _snippet_is_relevant(row: dict, event_name: str) -> bool:
    title = (row.get("title") or "").lower()
    content = (row.get("content") or "").lower()
    url = (row.get("url") or "").lower()
    blob = f"{title} {content} {url}"

    if not any(k in blob for k in _SPONSOR_KEYWORDS):
        return False

    # Drop wrong-city Tech Week etc.
    if "techweekgr.com" in url or "grand rapids" in blob:
        return False

    event_tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", event_name) if len(t) > 3]
    geo = ("miami", "florida", "south florida", "miami beach", "wynwood", "brickell")
    if any(t in blob for t in event_tokens):
        return True
    if any(g in blob for g in geo):
        return True

    # Press release naming one sponsor for this event is still useful
    if "/press-release" in url or "prnewswire" in url or "businesswire" in url:
        return any(t in blob for t in event_tokens)

    return False


def gather_event_sponsor_context(event_name: str, search_queries: list[str]) -> dict[str, Any]:
    """
    1–2 Tavily searches per event → advanced answer + filtered snippets.
    Typically 1–2 credits per query (basic) or 2 per query (advanced).
    """
    client = _tavily_client()
    depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip()
    answer_mode = os.getenv("TAVILY_INCLUDE_ANSWER", "advanced").strip()
    max_results = int(os.getenv("TAVILY_MAX_RESULTS", "8"))

    answers: list[str] = []
    snippets: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    queries = search_queries[:2] if search_queries else [f"{event_name} official sponsors partners Miami"]
    for raw_q in queries:
        query = f"{raw_q} Miami Florida sponsor partner brand names"
        resp = client.search(
            query=query,
            search_depth=depth,
            max_results=max_results,
            include_answer=answer_mode,
            exclude_domains=_exclude_domains(),
        )
        ans = (resp.get("answer") or "").strip()
        if ans:
            answers.append(ans)

        for row in resp.get("results") or []:
            url = (row.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            if not _snippet_is_relevant(row, event_name):
                continue
            seen_urls.add(url)
            snippets.append(
                {
                    "title": (row.get("title") or "").strip()[:200],
                    "content": (row.get("content") or "").strip()[:500],
                    "url": url,
                    "score": str(row.get("score") or ""),
                }
            )

    return {
        "event_name": event_name,
        "answer": "\n\n".join(answers),
        "snippets": snippets[:12],
    }
