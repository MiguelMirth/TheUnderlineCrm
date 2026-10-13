"""
Run execution: one in-process worker thread, FIFO over the SQLite queue.

Slice 1 runs a no-op source for every vertical so the queue, status, checkpoints,
and recovery work end to end with zero spend and zero Monday calls. Real stages
land in slices 2 and 3.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from engine.spend import BudgetStop
from engine.store import Store

log = logging.getLogger("engine.worker")

STAGE_FREE_GATES = 1

STAGE_NAMES: dict[int, str] = {
    0: "Source",
    1: "Free gates",
    2: "Org lookup",
    3: "Firmographics",
    4: "Spend evidence",
    5: "LLM QA",
    6: "Enrich",
    7: "Post-enrich gates",
}

# A stage handler gets the store and the run row. It returns a short summary string.
StageHandler = Callable[[Store, dict[str, Any]], str]


def _noop_source(store: Store, run: dict[str, Any]) -> str:
    store.add_event(
        run["id"],
        "warn",
        "No discovery source is wired in this build. The run exercised the queue only.",
    )
    return "no source wired"


def _retired_source(store: Store, run: dict[str, Any]) -> str:
    store.add_event(run["id"], "warn", "This vertical was removed from the preset. Nothing was searched.")
    return "vertical removed"


def handler_for(store: Store, run: dict[str, Any]) -> StageHandler:
    """Apollo people and research verticals use their lanes. Anything else is still a no-op."""
    if run.get("kind") == "import":
        raise RuntimeError("CSV import was removed.")
    if run["vertical_id"] in SOURCE_HANDLERS:
        return SOURCE_HANDLERS[run["vertical_id"]]
    from engine.presets import get_preset

    try:
        vertical = get_preset(run["preset_id"], store).vertical(run["vertical_id"])
    except KeyError:
        return _retired_source
    if vertical.source.kind == "apollo_people":
        from engine.apollo_lane import apollo_people_source

        return apollo_people_source
    if vertical.source.kind == "research_events":
        from engine.research_lane import research_source

        return research_source
    return _noop_source


SOURCE_HANDLERS: dict[str, StageHandler] = {}


def execute_run(store: Store, run: dict[str, Any]) -> str:
    """Run the stages from the saved checkpoint. Returns the final status."""
    run_id = run["id"]
    if run.get("cancel_requested"):
        store.set_status(run_id, "cancelled", stage_name="Cancelled")
        store.add_event(run_id, "info", "Cancelled before it started")
        return "cancelled"

    start_stage = int(run.get("stage") or 0)
    try:
        store.set_status(run_id, "running", stage=start_stage, stage_name=STAGE_NAMES.get(start_stage, "Source"))
        store.add_event(run_id, "info", f"Started at stage {start_stage} ({STAGE_NAMES.get(start_stage, 'Source')})")
        handler = handler_for(store, run)
        summary = handler(store, run)
        current = store.get_run(run_id) or {}
        if current.get("status") in ("awaiting_enrich", "cancelled", "budget_stopped"):
            store.add_event(run_id, "info", f"Stopped: {summary}")
            return current["status"]
        store.add_event(run_id, "info", f"Source finished: {summary}")

        counts = store.count_leads(run_id)
        final = "needs_review" if counts else "complete"
        store.set_status(run_id, final, stage_name="Review" if counts else "Done")
        store.add_event(run_id, "info", "Done" if final == "complete" else "Ready for review")
        return final
    except BudgetStop as exc:
        store.set_status(run_id, "budget_stopped", stage_name="Budget stopped", error=str(exc))
        store.add_event(run_id, "warn", f"Budget stopped: {exc}")
        return "budget_stopped"
    except Exception as exc:  # noqa: BLE001 - a failed run must be visible, not crash the worker
        log.exception("run %s failed", run_id)
        current = store.get_run(run_id) or {}
        stage = int(current.get("stage") or 0)
        message = f"{STAGE_NAMES.get(stage, 'Source')}: {exc}"
        store.set_status(run_id, "error", stage_name="Error", error=message[:500])
        store.add_event(run_id, "error", message)
        return "error"


class RunWorker:
    """Single daemon thread. Claims one queued run at a time."""

    def __init__(self, store: Store, *, poll_s: float = 2.0) -> None:
        self.store = store
        self.poll_s = poll_s
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.alive:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="engine-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def wake(self) -> None:
        self._wake.set()

    def run_once(self) -> bool:
        """Claim and execute one queued run. Returns False if the queue was empty."""
        run = self.store.claim_next_queued()
        if run is None:
            return False
        execute_run(self.store, run)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                did_work = self.run_once()
            except Exception:  # noqa: BLE001 - keep the worker alive; the error is logged
                log.exception("worker loop error")
                did_work = False
            if did_work:
                continue
            self._wake.wait(self.poll_s)
