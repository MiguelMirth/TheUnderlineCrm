"""
FastAPI app for the prospecting engine. Serves /api and the built UI on one origin.

Run: uv run uvicorn engine.api:app --app-dir src --host 127.0.0.1 --port 8765

The app binds to localhost (see README). Cloudflare Access sits in front; the
`Cf-Access-Authenticated-User-Email` header stamps who started a run or made a decision. There is no user table.
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from engine.crm import (
    CrmUnavailable,
    check_board_contract,
    columns_from_board,
    crm_blockers,
    crm_status,
    default_monday,
    ensure_snapshot,
    live_push_enabled,
    monday_api_key,
)
from engine.gates import approvable
from engine.models import (
    CrmStatus,
    DecisionResult,
    Estimate,
    EventOut,
    GateStep,
    Health,
    LeadBulkAction,
    LeadOut,
    Preset,
    PresetSettings,
    PushRequest,
    PushResult,
    RunCreate,
    RunOut,
    ToggleState,
    resolve_caps,
    resolve_toggle_values,
    toggle_states,
)
from engine.pipeline import RunWorker
from engine.presets import PRESETS, get_preset, validate_preset
from engine.presets.config import apply_settings, settings_from_preset
from engine.review import decide
from engine.spend import PROVIDERS, build_estimate, cache_fresh, probe_cache_key
from engine.store import RunInProgress, Store, write_daily_backup

log = logging.getLogger("engine.api")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "engine" / "underline.db"
DEFAULT_DIST = ROOT / "web" / "dist"
ACTOR_HEADER = "Cf-Access-Authenticated-User-Email"
LIVE_STATUSES = ("queued", "running", "enriching")


def _db_path() -> str:
    raw = os.getenv("ENGINE_DB_PATH", "").strip()
    if not raw:
        return str(DEFAULT_DB)
    path = Path(raw)
    return str(path if path.is_absolute() else ROOT / path)


def _actor(request: Request) -> str:
    return (request.headers.get(ACTOR_HEADER) or "").strip() or "local"


def _store(request: Request) -> Store:
    return request.app.state.store


def _worker(request: Request) -> RunWorker:
    return request.app.state.worker


_REMOVED_LABELS = {"park_adjacent": "Park-adjacent"}


def _run_out(store: Store, preset: Preset, run: dict[str, Any]) -> RunOut:
    try:
        vertical = preset.vertical(run["vertical_id"])
    except KeyError:
        vertical = None
    if vertical is None:
        toggles: list[ToggleState] = []
        label = _REMOVED_LABELS.get(run["vertical_id"], run["vertical_id"])
    else:
        # Stored toggles were validated at Start. Read them back without re-validating, so an
        # old run still renders if a preset later changes its toggle list.
        values = {spec.id: run["toggles"].get(spec.id, spec.default) for spec in vertical.toggles}
        toggles = toggle_states(vertical, values)
        label = vertical.label
    return RunOut(
        id=run["id"],
        kind=run["kind"],
        preset_id=run["preset_id"],
        vertical_id=run["vertical_id"],
        vertical_label=label,
        status=run["status"],
        stage=run["stage"],
        stage_name=run["stage_name"],
        toggles=toggles,
        caps=run["caps"],
        brief=run["brief"],
        started_by=run["started_by"],
        error=run["error"],
        cancel_requested=run["cancel_requested"],
        counts=store.count_leads(run["id"]),
        spend={p: store.ledger_run_total(run["id"], p) for p in PROVIDERS},
        reservation={k: float(v) for k, v in run["reservation"].items()},
        created_at=run["created_at"],
        updated_at=run["updated_at"],
    )


def _columns_for_board(board_id: str, fallback: dict[str, str]) -> tuple[dict[str, str], str]:
    """Column ids come from the live board's titles. Without a Monday key, the saved ids stay."""
    if not board_id.isdigit() or not monday_api_key():
        return fallback, ""
    try:
        meta = default_monday().get_board_metadata(int(board_id))
    except Exception as exc:  # noqa: BLE001 - a failed read must not wipe the saved contract
        return fallback, f"Could not read the Monday board: {exc}"
    if not meta:
        return fallback, "Monday did not return that board."
    mapped, missing = columns_from_board(meta)
    if missing:
        return fallback, "The board is missing columns: " + ", ".join(missing) + "."
    return mapped, ""


def _preset_or_404(preset_id: str, store: Optional[Store] = None) -> Preset:
    try:
        return get_preset(preset_id, store)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown preset {preset_id!r}") from exc


def _vertical_or_404(preset: Preset, vertical_id: str):
    try:
        return preset.vertical(vertical_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown vertical {vertical_id!r}") from exc


def _plan(store: Store, preset_id: str, vertical_id: str, toggles: dict[str, Any], caps: dict[str, int]):
    """Validate a payload against the preset. Returns (preset, vertical, toggle values, caps)."""
    preset = _preset_or_404(preset_id, store)
    vertical = _vertical_or_404(preset, vertical_id)
    try:
        values = resolve_toggle_values(vertical, toggles)
        resolved_caps = resolve_caps(vertical, caps)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return preset, vertical, values, resolved_caps


def _estimate_for(
    store: Store, preset: Preset, vertical: Any, values: dict[str, Any], caps: Any, *, brief: str = ""
) -> Estimate:
    """Cap estimate, replaced by a cached free-probe count when Concert or Venue has been measured."""
    probe = None
    if vertical.source.kind == "apollo_people":
        hit = cache_fresh(store, "engine", "probe", probe_cache_key(vertical.id, values, caps))
        if isinstance(hit, dict):
            probe = hit
    return build_estimate(store, preset, vertical, values, caps, probe=probe, brief=brief)


def _with_crm(store: Store, preset: Preset, estimate: Estimate, extra: Optional[list[str]] = None) -> Estimate:
    """Add CRM-side Start blockers (missing key, stale snapshot, invalid board contract) to the estimate."""
    blockers = list(estimate.blockers) + crm_blockers(store, preset) + list(extra or [])
    return estimate.model_copy(update={"blockers": blockers, "can_start": not blockers})


def _contract_problems(app: FastAPI) -> list[str]:
    status = getattr(app.state, "board_contract", None) or {}
    if status.get("checked") and not status.get("ok"):
        return list(status.get("problems") or ["The Monday board contract is not valid."])
    return []


def refresh_board_contract(app: FastAPI) -> dict[str, Any]:
    """Read the live board once. No key means the check is skipped; Start still needs a snapshot."""
    from engine.presets import get_preset

    preset = get_preset("underline", app.state.store)
    factory = getattr(app.state, "monday_factory", None)
    if factory is None and not monday_api_key():
        result = {"checked": False, "ok": True, "problems": []}
        app.state.board_contract = result
        return result
    try:
        monday = (factory or default_monday)()
        problems = check_board_contract(monday, preset)
        result = {"checked": True, "ok": not problems, "problems": problems}
    except Exception as exc:  # noqa: BLE001 - a failed check blocks push, it does not crash startup
        result = {"checked": True, "ok": False, "problems": [f"Board contract check failed: {exc}"]}
    app.state.board_contract = result
    return result


def _backup_loop(store: Store, db_path: str, stop: threading.Event) -> None:
    """Write today's database copy, then check again every six hours."""
    while not stop.is_set():
        try:
            dest = write_daily_backup(store, db_path)
            if dest:
                log.info("database backup %s", dest)
        except Exception:
            log.exception("database backup failed")
        if stop.wait(6 * 60 * 60):
            return


def create_app(
    *,
    db_path: Optional[str] = None,
    start_worker: bool = True,
    dist_dir: Optional[Path] = None,
    load_env: bool = True,
    monday_factory: Optional[Callable[[], Any]] = None,
) -> FastAPI:
    """
    load_env reads the repo .env into os.environ when the server starts. Tests pass False:
    loading .env at import time would leak real keys and flags into every other test.
    monday_factory builds the Monday client used for CRM reads. Tests inject a fake.
    """
    dist = Path(dist_dir) if dist_dir else DEFAULT_DIST

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if load_env:
            load_dotenv(ROOT / ".env", override=False)
        path = db_path or _db_path()
        store = Store(path)
        store.recover_interrupted()
        worker = RunWorker(store)
        app.state.store = store
        app.state.worker = worker
        app.state.db_path = path
        app.state.monday_factory = monday_factory
        app.state.board_contract = {"checked": False, "ok": True, "problems": []}
        refresh_board_contract(app)
        backup_stop = threading.Event()
        backup_thread: threading.Thread | None = None
        if start_worker:
            worker.start()
            backup_thread = threading.Thread(
                target=_backup_loop, args=(store, path, backup_stop), name="engine-backup", daemon=True
            )
            backup_thread.start()
        try:
            yield
        finally:
            backup_stop.set()
            worker.stop()
            if backup_thread:
                backup_thread.join(timeout=2)

    app = FastAPI(title="The Underline prospecting engine", version="1", lifespan=lifespan)

    # -- health and presets -------------------------------------------------

    @app.get("/api/health", response_model=Health)
    def health(request: Request) -> Health:
        contract = getattr(request.app.state, "board_contract", None) or {}
        return Health(
            ok=True,
            db_path=request.app.state.db_path,
            schema_version=_store(request).schema_version(),
            worker_alive=_worker(request).alive,
            ui_built=(dist / "index.html").is_file(),
            live_push_enabled=live_push_enabled(),
            board_contract_ok=bool(contract.get("ok", True)),
            board_contract_problems=list(contract.get("problems") or []),
        )

    @app.get("/api/presets", response_model=list[Preset])
    def list_presets(request: Request) -> list[Preset]:
        store = _store(request)
        return [get_preset(preset_id, store) for preset_id in PRESETS]

    @app.get("/api/presets/{preset_id}", response_model=Preset)
    def one_preset(preset_id: str, request: Request) -> Preset:
        return _preset_or_404(preset_id, _store(request))

    @app.get("/api/presets/{preset_id}/problems", response_model=list[str])
    def preset_problems(preset_id: str, request: Request) -> list[str]:
        return validate_preset(_preset_or_404(preset_id, _store(request)))

    @app.get("/api/presets/{preset_id}/settings", response_model=PresetSettings)
    def get_preset_settings(preset_id: str, request: Request) -> PresetSettings:
        if preset_id not in PRESETS:
            raise HTTPException(status_code=404, detail=f"unknown preset {preset_id!r}")
        store = _store(request)
        return settings_from_preset(get_preset(preset_id, store), PRESETS[preset_id])

    @app.put("/api/presets/{preset_id}/settings", response_model=PresetSettings)
    def put_preset_settings(preset_id: str, payload: PresetSettings, request: Request) -> PresetSettings:
        if preset_id not in PRESETS:
            raise HTTPException(status_code=404, detail=f"unknown preset {preset_id!r}")
        columns, problem = _columns_for_board(payload.board_id.strip(), payload.columns)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
        payload = payload.model_copy(update={"columns": columns})
        try:
            apply_settings(PRESETS[preset_id], payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store = _store(request)
        store.put_preset_settings(preset_id, payload.model_dump())
        refresh_board_contract(request.app)
        return settings_from_preset(get_preset(preset_id, store), PRESETS[preset_id])

    @app.post("/api/presets/{preset_id}/settings/reset", response_model=PresetSettings)
    def reset_preset_settings(preset_id: str, request: Request) -> PresetSettings:
        if preset_id not in PRESETS:
            raise HTTPException(status_code=404, detail=f"unknown preset {preset_id!r}")
        store = _store(request)
        store.delete_preset_settings(preset_id)
        refresh_board_contract(request.app)
        factory = PRESETS[preset_id]
        return settings_from_preset(factory, factory)

    # -- CRM snapshot -------------------------------------------------------

    @app.get("/api/crm/status", response_model=CrmStatus)
    def get_crm_status(request: Request, preset_id: str = "underline") -> CrmStatus:
        preset = _preset_or_404(preset_id, _store(request))
        return CrmStatus(**crm_status(_store(request), preset))

    @app.post("/api/crm/refresh", response_model=CrmStatus)
    def refresh_crm(request: Request, preset_id: str = "underline") -> CrmStatus:
        store = _store(request)
        preset = _preset_or_404(preset_id, store)
        live = [r for r in store.list_runs(limit=50) if r["status"] in LIVE_STATUSES]
        if live:
            raise HTTPException(
                status_code=409,
                detail=f"A run is live ({live[0]['id']}). The snapshot only refreshes between runs.",
            )
        try:
            ensure_snapshot(store, preset, monday_factory=request.app.state.monday_factory, force=True)
        except CrmUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return CrmStatus(**crm_status(store, preset))

    # -- estimate and runs --------------------------------------------------

    @app.post("/api/estimate", response_model=Estimate)
    def estimate(payload: RunCreate, request: Request, probe: bool = False) -> Estimate:
        store = _store(request)
        preset, vertical, values, caps = _plan(store, payload.preset_id, payload.vertical_id, payload.toggles, payload.caps)
        if probe and vertical.source.kind == "apollo_people":
            from engine.apollo_lane import free_probe

            try:
                counts = free_probe(store, preset, vertical, values, caps)
            except Exception as exc:  # noqa: BLE001 - the operator sees the reason, the process stays up
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            store.cache_put("engine", "probe", probe_cache_key(vertical.id, values, caps), counts, 0)
            est = build_estimate(store, preset, vertical, values, caps, probe=counts, brief=payload.brief)
        else:
            est = _estimate_for(store, preset, vertical, values, caps, brief=payload.brief)
        return _with_crm(store, preset, est, _contract_problems(request.app))

    @app.post("/api/runs", response_model=RunOut, status_code=201)
    def create_run(payload: RunCreate, request: Request) -> RunOut:
        store = _store(request)
        preset, vertical, values, caps = _plan(store, payload.preset_id, payload.vertical_id, payload.toggles, payload.caps)
        est = _with_crm(
            store, preset, _estimate_for(store, preset, vertical, values, caps, brief=payload.brief),
            _contract_problems(request.app),
        )
        if not est.can_start:
            raise HTTPException(status_code=409, detail={"blockers": est.blockers})
        reservation = {p.provider: float(p.total or 0) for p in est.providers if p.total}
        run = store.create_run(
            kind="discovery",
            preset_id=preset.id,
            vertical_id=vertical.id,
            toggles=values,
            caps=caps.model_dump(),
            brief=payload.brief.strip(),
            started_by=_actor(request),
            reservation=reservation,
        )
        _worker(request).wake()
        return _run_out(store, preset, run)

    @app.get("/api/runs", response_model=list[RunOut])
    def list_runs(request: Request, limit: int = 30) -> list[RunOut]:
        store = _store(request)
        out: list[RunOut] = []
        for run in store.list_runs(limit=max(1, min(limit, 200))):
            try:
                preset = get_preset(run["preset_id"], store)
            except KeyError:
                continue
            out.append(_run_out(store, preset, run))
        return out

    def _run_or_404(request: Request, run_id: str) -> dict[str, Any]:
        run = _store(request).get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/api/runs/{run_id}", response_model=RunOut)
    def get_run(run_id: str, request: Request) -> RunOut:
        run = _run_or_404(request, run_id)
        return _run_out(_store(request), get_preset(run["preset_id"], _store(request)), run)

    @app.get("/api/runs/{run_id}/events", response_model=list[EventOut])
    def run_events(run_id: str, request: Request, limit: int = 200) -> list[EventOut]:
        _run_or_404(request, run_id)
        return [EventOut(**e) for e in _store(request).list_events(run_id, limit=max(1, min(limit, 1000)))]

    @app.get("/api/runs/{run_id}/leads", response_model=list[LeadOut])
    def run_leads(run_id: str, request: Request, state: Optional[str] = None) -> list[LeadOut]:
        _run_or_404(request, run_id)
        states = [s for s in (state or "").split(",") if s] or None
        return [_lead_out(r) for r in _store(request).list_leads(run_id, states)]

    @app.post("/api/runs/{run_id}/leads/decide", response_model=DecisionResult)
    def decide_leads(run_id: str, payload: LeadBulkAction, request: Request) -> DecisionResult:
        _run_or_404(request, run_id)
        result = decide(_store(request), run_id, payload.action, payload.lead_ids, _actor(request))
        if payload.action == "approve" and result["refused"]:
            # Approve is all-or-nothing. The body names every refused lead and its reason.
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Some leads cannot be approved. Nothing was approved.",
                    "refused": result["refused"],
                },
            )
        return DecisionResult(**result)

    @app.post("/api/runs/{run_id}/push", response_model=PushResult)
    def push_run(run_id: str, payload: PushRequest, request: Request) -> PushResult:
        from engine.push import PushRefused, push_leads

        store = _store(request)
        run = _run_or_404(request, run_id)
        try:
            result = push_leads(
                store,
                get_preset(run["preset_id"], store),
                run_id,
                actor=_actor(request),
                lead_ids=payload.lead_ids,
                monday_factory=request.app.state.monday_factory,
            )
        except PushRefused as exc:
            raise HTTPException(status_code=409, detail=exc.message) from exc
        return PushResult(**result)

    @app.post("/api/runs/{run_id}/enrich", response_model=RunOut)
    def enrich_run(run_id: str, request: Request) -> RunOut:
        store = _store(request)
        run = _run_or_404(request, run_id)
        shortlisted = store.count_leads(run_id).get("shortlisted", 0)
        if shortlisted <= 0:
            raise HTTPException(status_code=409, detail="No contacts are shortlisted.")
        status = run["status"]
        if status == "awaiting_enrich":
            pass
        elif status in ("needs_review", "complete"):
            # A restored shortlist lead can be enriched after the pause. Stage 6 only buys those leads.
            vertical = get_preset(run["preset_id"], store).vertical(run["vertical_id"])
            if vertical.source.kind == "csv":
                raise HTTPException(status_code=409, detail="Imported contacts are already enriched.")
        else:
            raise HTTPException(status_code=409, detail=f"run is {status}, not waiting to enrich")
        store.set_status(run_id, "queued", stage=6, stage_name="Enrich")
        store.add_event(run_id, "info", f"Enrich queued for {shortlisted} contact(s), {shortlisted} Apollo credits")
        _worker(request).wake()
        fresh = store.get_run(run_id) or run
        return _run_out(store, get_preset(fresh["preset_id"], store), fresh)

    @app.post("/api/runs/{run_id}/resume", response_model=RunOut)
    def resume_run(run_id: str, request: Request) -> RunOut:
        store = _store(request)
        run = _run_or_404(request, run_id)
        if run["status"] not in ("interrupted", "budget_stopped", "error"):
            raise HTTPException(status_code=409, detail=f"run is {run['status']}, not resumable")
        run = store.queue_resume(run_id) or run
        _worker(request).wake()
        return _run_out(store, get_preset(run["preset_id"], store), run)

    @app.post("/api/runs/{run_id}/cancel", response_model=RunOut)
    def cancel_run(run_id: str, request: Request) -> RunOut:
        store = _store(request)
        _run_or_404(request, run_id)
        run = store.request_cancel(run_id) or {}
        return _run_out(store, get_preset(run["preset_id"], store), run)

    @app.delete("/api/runs/{run_id}", status_code=204)
    def delete_run(run_id: str, request: Request) -> Response:
        store = _store(request)
        try:
            deleted = store.delete_run(run_id)
        except RunInProgress as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="run not found")
        return Response(status_code=204)

    # -- UI -----------------------------------------------------------------

    def _spa(full_path: str) -> Any:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        index = dist / "index.html"
        if not index.is_file():
            return PlainTextResponse(
                "The UI is not built yet. Run: npm --prefix web run build",
                status_code=503,
            )
        if full_path:
            candidate = (dist / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
        return FileResponse(index)

    @app.get("/", include_in_schema=False)
    def spa_root() -> Any:
        return _spa("")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Any:
        return _spa(full_path)

    return app


def _lead_out(row: dict[str, Any]) -> LeadOut:
    gates = [GateStep(**g) for g in row["gates"]]
    ok, reason = approvable(row)
    return LeadOut(
        id=row["id"],
        run_id=row["run_id"],
        seq=row["seq"],
        state=row["state"],
        shelf_brand=row["shelf_brand"],
        person_name=row["person_name"],
        title=row["title"],
        email=row["email"],
        domain=row["domain"],
        location=row["location"],
        vertical=row["vertical"],
        gates=gates,
        llm=row["llm"],
        evidence=row["evidence"],
        cost_spent=row["cost_spent"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        monday_item_id=row["monday_item_id"],
        push_error=row["push_error"],
        approvable=ok,
        approve_blocker="" if ok else reason,
    )


app = create_app()
