"""
Shared I/O parallelism for prospecting research (sponsor events + park segments).

Cursor Cloud + Tavily calls are network-bound; running a few in parallel cuts wall
clock without changing extract/score quality. Tune with PROSPECT_RESEARCH_WORKERS.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def research_worker_count(default: int = 3) -> int:
    raw = os.getenv("PROSPECT_RESEARCH_WORKERS", str(default)).strip()
    try:
        n = int(raw)
    except ValueError:
        n = default
    return max(1, min(n, 8))


def map_parallel(
    items: Sequence[T],
    fn: Callable[[T], R],
    *,
    max_workers: int | None = None,
) -> List[R]:
    """
    Run ``fn`` over ``items`` with a thread pool. Results keep input order.
    Errors from ``fn`` propagate (same as a serial loop).
    """
    if not items:
        return []
    workers = max_workers if max_workers is not None else research_worker_count()
    if workers <= 1 or len(items) == 1:
        return [fn(item) for item in items]

    results: list[R | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        futures = {pool.submit(fn, item): idx for idx, item in enumerate(items)}
        for fut in as_completed(futures):
            idx = futures[fut]
            results[idx] = fut.result()
    return [r for r in results]  # type: ignore[misc]
