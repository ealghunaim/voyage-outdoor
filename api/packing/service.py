"""Smart Pack generation: load, run the engines, persist (§8).

The pipeline, and the shape VoyageOS's packing service earned:

    context -> engines -> persist with a full snapshot

with one difference that matters more here than it did there: NO MODEL IS IN
THIS PATH AT ALL. VoyageOS asks a model for a list and then overrides its
quantities; this asks nothing. Phase 4's narrative reads what this writes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from api.engines import gear_health, pack
from api.engines.pack import PackResult

#: States a person has moved an item into. Regeneration must not throw these
#: away — see _carry_over.
MEANINGFUL_STATES = ("selected", "packed", "verified", "in_use", "returned",
                     "missing", "damaged")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_context(db, adventure: dict, user_id: str) -> tuple[list[dict], list[dict], dict]:
    """The locker, the forecast, and health for every item — in three queries.

    Usage is fetched once for the whole locker and grouped here rather than
    per item. Forty items would otherwise be forty round trips, and on this
    deployment each one crosses from the API to Postgres.
    """
    locker = (db.table("gear_items").select("*")
              .eq("user_id", user_id).eq("status", "active").execute().data)

    weather = (db.table("weather_snapshots").select("*")
               .eq("adventure_id", adventure["id"])
               .order("forecast_date").execute().data)

    ids = [g["id"] for g in locker]
    usage = ((db.table("gear_usage").select("gear_item_id,distance_m,duration_s")
              .in_("gear_item_id", ids).execute().data) if ids else [])

    totals: dict[str, dict] = {}
    for row in usage:
        bucket = totals.setdefault(row["gear_item_id"],
                                   {"distance_m": 0, "duration_s": 0, "sessions": 0})
        bucket["distance_m"] += row.get("distance_m") or 0
        bucket["duration_s"] += row.get("duration_s") or 0
        bucket["sessions"] += 1

    health = {g["id"]: gear_health.evaluate(g, totals.get(g["id"], {}))
              for g in locker}
    return locker, weather, health


def _carry_over(existing: list[dict], result: PackResult) -> dict[str, str]:
    """Pack states that survive a regeneration, keyed by what they were about.

    WHY THIS EXISTS. Regenerating because the forecast changed the day before a
    race must not un-pack a bag that is already packed. Someone with 43 of 47
    items ticked off would lose the lot, and after that happens once nobody
    regenerates again — which means they run on a stale list, which is worse
    than the problem the regeneration was solving.

    Keyed on gear_item_id where there is one, and on the item's NAME where
    there is not, because an unmatched mandatory line ("Ceremonial trebuchet")
    has no gear behind it and is still a thing someone has physically put in a
    bag.

    Only meaningful states carry. `not_selected` is the default and carrying it
    would pin an item to a stale decision after a rule changed its
    classification.
    """
    carried: dict[str, str] = {}
    for row in existing:
        state = row.get("state")
        if state not in MEANINGFUL_STATES:
            continue
        key = row.get("gear_item_id") or f"name:{row.get('name')}"
        carried[key] = state
    return carried


def generate(db, adventure: dict, user_id: str) -> dict:
    """Build (or rebuild) the pack for one adventure and store it."""
    locker, weather, health = load_context(db, adventure, user_id)
    result = pack.generate(adventure, locker, weather, health=health)

    existing_list = (db.table("packing_lists").select("id")
                     .eq("adventure_id", adventure["id"]).execute().data)
    existing_items: list[dict] = []
    if existing_list:
        existing_items = (db.table("packing_list_items").select("*")
                          .eq("list_id", existing_list[0]["id"]).execute().data)
    carried = _carry_over(existing_items, result)

    # ONE LIST PER ADVENTURE (0003). The old one and its items and warnings go
    # first; the unique constraint makes a second impossible anyway, and
    # deleting explicitly means the cascade is visible here rather than
    # implied.
    if existing_list:
        db.table("packing_lists").delete().eq("id", existing_list[0]["id"]).execute()

    snapshot = {**result.snapshot, "carried_states": len(carried)}
    list_row = db.table("packing_lists").insert({
        "adventure_id": adventure["id"],
        "ruleset_version": result.ruleset,
        "generation_snapshot": snapshot,
    }).execute().data[0]

    items = []
    for sort, line in enumerate(result.lines):
        key = line.gear_item_id or f"name:{line.name}"
        items.append({
            "list_id": list_row["id"],
            "gear_item_id": line.gear_item_id,
            "name": line.name,
            "category_key": line.category_key,
            "qty": line.qty,
            "classification": line.classification,
            "state": carried.get(key, "not_selected"),
            "critical": line.critical,
            "rule_key": line.rule_key,
            "reason": line.reason,
            "source": line.source,
            "sort": sort,
        })
    if items:
        db.table("packing_list_items").insert(items).execute()

    warnings = [{
        "list_id": list_row["id"],
        "gear_item_id": w.gear_item_id,
        "key": w.key, "severity": w.severity, "message": w.message,
        "rule_key": w.rule_key, "detail": w.detail,
    } for w in result.warnings]
    if warnings:
        db.table("pack_warnings").insert(warnings).execute()

    # Health is stored on the gear itself, not on the pack: it is a property of
    # the shoes rather than of this race, and the locker list reads it without
    # having generated a pack at all.
    for gear_id, health_result in health.items():
        db.table("gear_items").update({
            "condition_pct": health_result.condition_pct,
            "health_ruleset": health_result.ruleset,
            "health_detail": {**health_result.detail,
                              "state": health_result.state,
                              "message": health_result.message},
            "health_evaluated_at": _now(),
        }).eq("id", gear_id).execute()

    return read(db, adventure)


def read(db, adventure: dict) -> dict:
    """The stored pack, its warnings, and the readiness figure."""
    rows = (db.table("packing_lists").select("*")
            .eq("adventure_id", adventure["id"]).execute().data)
    if not rows:
        return {"list": None, "items": [], "warnings": [],
                "readiness": pack.readiness([])}

    list_row = rows[0]
    items = (db.table("packing_list_items").select("*")
             .eq("list_id", list_row["id"]).order("sort").execute().data)
    warnings = (db.table("pack_warnings").select("*")
                .eq("list_id", list_row["id"]).execute().data)
    return {"list": list_row, "items": items, "warnings": warnings,
            "readiness": pack.readiness(items)}
