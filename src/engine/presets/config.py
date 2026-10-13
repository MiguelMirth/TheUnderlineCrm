"""
Apply the Preset screen onto the factory Underline preset.

The factory preset in code is the reset point. A saved document replaces the
search lists, Monday contract, cap defaults, and gate defaults. It cannot add
a vertical or change which gates exist.
"""
from __future__ import annotations

from engine.crm import board_id, new_leads_group_id
from engine.models import (
    Caps,
    PersonTier,
    Preset,
    PresetSettings,
    ToggleDefault,
    VerticalSettings,
    VerticalSpec,
    resolve_toggle_values,
)


def editable_cap_keys(vertical: VerticalSpec) -> list[str]:
    """Cap defaults the Preset screen shows. Per-run limits on Gather are a separate set."""
    if vertical.source.kind == "research_events":
        return ["events", "brands", "queries_per_source"]
    keys = ["target", "max_pages", "title_chunk", "org_pages"]
    if vertical.id == "concert_series":
        keys.extend(["tavily_batch", "gemini_batch"])
    elif vertical.llm_qa == "gemini":
        keys.append("gemini_batch")
    return keys


def clean_lines(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        line = str(raw).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def _seed_problem(path: str) -> str:
    raw = path.strip().replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    parts = [part for part in raw.split("/") if part]
    if ".." in parts or not raw.startswith("data/") or not raw.endswith(".json"):
        return "Seed path must be a JSON file under data/."
    return ""


def settings_problems(factory: Preset, settings: PresetSettings) -> list[str]:
    """Reasons a save should be refused. Empty means the document can be applied."""
    problems: list[str] = []
    board = settings.board_id.strip()
    if not board.isdigit():
        problems.append("Board id must be the numeric Monday board id.")
    group = settings.new_leads_group_id.strip()
    if not group or any(ch.isspace() for ch in group):
        problems.append("New leads group id is required.")

    missing = [key for key in factory.crm.columns if not str(settings.columns.get(key) or "").strip()]
    if missing:
        problems.append("Monday column ids are missing: " + ", ".join(missing) + ".")
    extra = sorted(set(settings.columns) - set(factory.crm.columns))
    if extra:
        problems.append("Unknown Monday columns: " + ", ".join(extra) + ".")

    got = [vertical.id for vertical in settings.verticals]
    want = [vertical.id for vertical in factory.verticals]
    if sorted(got) != sorted(want) or len(got) != len(want):
        problems.append("Preset verticals do not match this build.")
        return problems

    by_id = {vertical.id: vertical for vertical in settings.verticals}
    for vertical in factory.verticals:
        edit = by_id[vertical.id]
        prefix = vertical.label
        if not clean_lines(edit.titles):
            problems.append(f"{prefix}: add at least one search title.")
        if not clean_lines(edit.seniorities):
            problems.append(f"{prefix}: add at least one seniority.")
        if vertical.source.kind == "apollo_people":
            if not clean_lines(edit.org_keyword_tags):
                problems.append(f"{prefix}: add at least one org keyword.")
            if not clean_lines(edit.org_locations):
                problems.append(f"{prefix}: add at least one org location.")
            factory_tiers = {int(row["tier"]) for row in (vertical.source.params.get("person_location_tiers") or [])}
            edit_tiers = {int(row.tier): clean_lines(row.locations) for row in edit.person_location_tiers}
            if set(edit_tiers) != factory_tiers:
                problems.append(f"{prefix}: person location tiers do not match this build.")
            elif any(not locs for locs in edit_tiers.values()):
                problems.append(f"{prefix}: each person location tier needs at least one place.")
            if vertical.monday_vertical != "from_research" and not edit.monday_vertical.strip():
                problems.append(f"{prefix}: Monday vertical label is required.")
        if "seed_path" in vertical.source.params:
            seed_problem = _seed_problem(edit.seed_path)
            if seed_problem:
                problems.append(f"{prefix}: {seed_problem}")
        if "florida_person_locations" in vertical.source.params and not clean_lines(edit.florida_person_locations):
            problems.append(f"{prefix}: add at least one Florida person location.")
        if "us_person_locations" in vertical.source.params and not clean_lines(edit.us_person_locations):
            problems.append(f"{prefix}: add at least one US person location.")

        allowed = set(editable_cap_keys(vertical))
        unknown = sorted(set(edit.caps) - allowed)
        if unknown:
            problems.append(f"{prefix}: unknown limits: " + ", ".join(unknown) + ".")
        if allowed - set(edit.caps):
            problems.append(f"{prefix}: limits are incomplete.")
        for key, value in edit.caps.items():
            if key in allowed and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                problems.append(f"{prefix}: {key} must be a non-negative whole number.")

        ids = [toggle.id for toggle in edit.toggles]
        factory_ids = [toggle.id for toggle in vertical.toggles]
        if sorted(ids) != sorted(factory_ids) or len(ids) != len(factory_ids):
            problems.append(f"{prefix}: gates do not match this build.")
        else:
            try:
                resolve_toggle_values(vertical, {toggle.id: toggle.value for toggle in edit.toggles})
            except ValueError as exc:
                problems.append(f"{prefix}: {exc}")
    return problems


def apply_settings(factory: Preset, settings: PresetSettings) -> Preset:
    """Return a preset with the saved document applied. Raises ValueError when it is unsafe."""
    problems = settings_problems(factory, settings)
    if problems:
        raise ValueError(" ".join(problems))

    columns = {key: str(settings.columns[key]).strip() for key in factory.crm.columns}
    crm = factory.crm.model_copy(
        update={
            "board_id_override": settings.board_id.strip(),
            "new_leads_group_override": settings.new_leads_group_id.strip(),
            "columns": columns,
            "protected_group_ids": clean_lines(settings.protected_group_ids),
            "protected_status_labels": clean_lines(settings.protected_status_labels),
        }
    )
    by_id = {vertical.id: vertical for vertical in settings.verticals}
    verticals: list[VerticalSpec] = []
    for vertical in factory.verticals:
        edit = by_id[vertical.id]
        params = dict(vertical.source.params)
        params["titles"] = clean_lines(edit.titles)
        params["seniorities"] = clean_lines(edit.seniorities)
        if vertical.source.kind == "apollo_people":
            params["org_keyword_tags"] = clean_lines(edit.org_keyword_tags)
            params["org_locations"] = clean_lines(edit.org_locations)
            params["person_location_tiers"] = [
                {"tier": int(row.tier), "locations": clean_lines(row.locations)}
                for row in sorted(edit.person_location_tiers, key=lambda item: item.tier)
            ]
        if "seed_path" in vertical.source.params:
            params["seed_path"] = edit.seed_path.strip().replace("\\", "/")
        if "florida_person_locations" in vertical.source.params:
            params["florida_person_locations"] = clean_lines(edit.florida_person_locations)
        if "us_person_locations" in vertical.source.params:
            params["us_person_locations"] = clean_lines(edit.us_person_locations)

        caps = vertical.caps.model_dump()
        for key in editable_cap_keys(vertical):
            caps[key] = int(edit.caps[key])
        saved_toggles = {toggle.id: toggle.value for toggle in edit.toggles}
        toggles = [spec.model_copy(update={"default": saved_toggles[spec.id]}) for spec in vertical.toggles]
        monday = vertical.monday_vertical
        if monday != "from_research":
            monday = edit.monday_vertical.strip()
        verticals.append(
            vertical.model_copy(
                update={
                    "monday_vertical": monday,
                    "source": vertical.source.model_copy(update={"params": params}),
                    "caps": Caps(**caps),
                    "toggles": toggles,
                }
            )
        )
    return factory.model_copy(update={"crm": crm, "verticals": verticals})


def settings_from_preset(effective: Preset, factory: Preset) -> PresetSettings:
    """The form document. Values come from the saved preset; code_default stays the factory value."""
    factory_by_id = {vertical.id: vertical for vertical in factory.verticals}
    verticals: list[VerticalSettings] = []
    for vertical in effective.verticals:
        origin = factory_by_id[vertical.id]
        params = vertical.source.params
        origin_toggles = {spec.id: spec for spec in origin.toggles}
        toggles = [
            ToggleDefault(
                id=spec.id,
                label=spec.label,
                kind=spec.kind,
                value=spec.default,
                code_default=origin_toggles[spec.id].default,
                choices=spec.choices,
                relaxed_when=spec.relaxed_when,
            )
            for spec in vertical.toggles
        ]
        tiers = [
            PersonTier(tier=int(row["tier"]), locations=list(row.get("locations") or []))
            for row in (params.get("person_location_tiers") or [])
        ]
        caps = vertical.caps.model_dump()
        verticals.append(
            VerticalSettings(
                id=vertical.id,
                label=origin.label,
                source_kind=vertical.source.kind,
                monday_vertical=vertical.monday_vertical,
                titles=list(params.get("titles") or []),
                seniorities=list(params.get("seniorities") or []),
                org_keyword_tags=list(params.get("org_keyword_tags") or []),
                org_locations=list(params.get("org_locations") or []),
                person_location_tiers=tiers,
                florida_person_locations=list(params.get("florida_person_locations") or []),
                us_person_locations=list(params.get("us_person_locations") or []),
                seed_path=str(params.get("seed_path") or ""),
                caps={key: int(caps[key]) for key in editable_cap_keys(vertical)},
                toggles=toggles,
            )
        )
    return PresetSettings(
        board_id=board_id(effective.crm),
        new_leads_group_id=new_leads_group_id(effective.crm),
        columns=dict(effective.crm.columns),
        protected_group_ids=list(effective.crm.protected_group_ids),
        protected_status_labels=list(effective.crm.protected_status_labels),
        verticals=verticals,
    )
