"""Adventures — the central planning object (Master Prompt §7).

FULLY SEPARATE FROM VoyageOS'S TRIP (§0.7). Different project, different
database, and a different shape: a trip has destinations and travellers, an
adventure has a distance, an elevation profile and a mandatory kit list. The
pressure to make this "a trip with a distance" arrives during implementation,
not during design, which is why it is written down here as well as in the
schema.

The activity-specific half of an adventure lives in `attributes`, validated
against the registry by the same code that validates gear. Nothing in this file
knows what a trail race is.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from api.activities.registry import ACTIVITIES, BUILT
from api.activities.validate import validate_adventure_attributes
from api.core.access import owned_adventure
from api.core.auth import current_user_id
from api.core.db import get_db

router = APIRouter(prefix="/v1/adventures", tags=["adventures"])

#: A closed set the code branches on.
#:
#: draft      being planned; incomplete by definition
#: planned    committed to — this is what Smart Pack generates against
#: active     happening now
#: completed  done, and the usage logged against it is history
#: archived   out of the way without being deleted
STATUSES = ("draft", "planned", "active", "completed", "archived")

#: Which transitions are allowed. Written as data rather than as a chain of
#: ifs because the interesting part is what is MISSING: nothing returns to
#: draft once it is planned, and completed does not go back to active. An
#: adventure that has happened cannot un-happen, and a readiness score
#: recomputed for a finished race would be answering a question nobody asked.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft":     ("planned", "archived"),
    "planned":   ("active", "completed", "archived"),
    "active":    ("completed", "archived"),
    "completed": ("archived",),
    "archived":  ("planned",),        # unarchive, back to the planning state
}


class AdventureCreate(BaseModel):
    activity_key: str
    title: str = Field(min_length=1, max_length=140)
    subtype: str | None = Field(default=None, max_length=60)
    place_name: str | None = Field(default=None, max_length=140)
    country_code: str | None = Field(default=None, max_length=2)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    start_date: date
    end_date: date | None = None
    attributes: dict | None = None

    @field_validator("activity_key")
    @classmethod
    def _built_only(cls, v: str) -> str:
        # A schema-only activity has no screens and no rule set. Accepting one
        # here would put a fishing adventure in the database that nothing can
        # render and Smart Pack cannot reason about — a row that looks like a
        # feature and is a dead end.
        if v not in BUILT:
            known = ", ".join(BUILT)
            raise ValueError(f"{v} is not built yet — available: {known}")
        return v


class AdventurePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=140)
    subtype: str | None = Field(default=None, max_length=60)
    place_name: str | None = Field(default=None, max_length=140)
    country_code: str | None = Field(default=None, max_length=2)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    attributes: dict | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(payload: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
            for k, v in payload.items()}


@router.get("")
def list_adventures(status: str | None = Query(default=None),
                    upcoming: bool | None = None,
                    user_id: str = Depends(current_user_id)):
    """Adventures, soonest first.

    Archived is hidden unless asked for, the same rule the locker applies to
    retired gear: "what am I doing" and "everything I have ever planned" are
    different questions and the default should answer the first.
    """
    db = get_db()
    q = db.table("adventures").select("*").eq("user_id", user_id)
    if status == "all":
        pass
    elif status:
        if status not in STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(STATUSES)} or 'all'")
        q = q.eq("status", status)
    else:
        q = q.neq("status", "archived")
    if upcoming:
        q = q.gte("end_date", date.today().isoformat())
    return q.order("start_date").execute().data


@router.post("", status_code=201)
def create_adventure(body: AdventureCreate, user_id: str = Depends(current_user_id)):
    db = get_db()
    payload = _jsonable(body.model_dump(exclude={"attributes"}))
    payload["user_id"] = user_id
    # A single-day race is the common case, so end_date defaults to the start
    # rather than being required. The CHECK constraint in 0001 refuses the
    # reverse, and this is what keeps a one-day adventure from tripping it.
    payload["end_date"] = payload["end_date"] or payload["start_date"]
    if payload["end_date"] < payload["start_date"]:
        raise HTTPException(422, "end_date is before start_date")
    payload["attributes"] = validate_adventure_attributes(
        body.activity_key, body.attributes)
    return db.table("adventures").insert(payload).execute().data[0]


@router.get("/{adventure_id}")
def get_adventure(adventure_id: str, user_id: str = Depends(current_user_id)):
    """One adventure, with the weather already fetched for it.

    Weather is NOT fetched here. It is read from whatever snapshots exist, and
    refreshing is an explicit call — see api/weather/router.py. A GET that
    reaches a third-party API is a GET that fails when that API does, and this
    screen has to render on a phone with one bar at a trailhead.
    """
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id)
    adventure["weather"] = (
        db.table("weather_snapshots").select("*")
        .eq("adventure_id", adventure_id)
        .order("forecast_date").execute().data
    )
    adventure["usage"] = (
        db.table("gear_usage").select("*, gear_items(id,name,category_key)")
        .eq("adventure_id", adventure_id).execute().data
    )
    return adventure


@router.patch("/{adventure_id}")
def update_adventure(adventure_id: str, body: AdventurePatch,
                     user_id: str = Depends(current_user_id)):
    db = get_db()
    current = owned_adventure(db, adventure_id, user_id, writing=True)
    patch = body.model_dump(exclude_unset=True)

    if "status" in patch:
        want = patch["status"]
        if want not in STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(STATUSES)}")
        have = current["status"]
        if want != have and want not in TRANSITIONS[have]:
            allowed = ", ".join(TRANSITIONS[have]) or "nothing"
            raise HTTPException(
                409, f"An adventure that is {have} can only become {allowed}.")

    if "attributes" in patch:
        incoming = validate_adventure_attributes(
            current["activity_key"], patch["attributes"], partial=True)
        merged = {**(current.get("attributes") or {}), **incoming}
        for key, value in (patch["attributes"] or {}).items():
            if value is None:
                merged.pop(key, None)
        patch["attributes"] = merged

    start = patch.get("start_date", current["start_date"])
    end = patch.get("end_date", current["end_date"])
    if str(end) < str(start):
        raise HTTPException(422, "end_date is before start_date")

    patch["updated_at"] = _now()
    rows = db.table("adventures").update(_jsonable(patch)) \
        .eq("id", adventure_id).execute().data
    return rows[0] if rows else current


@router.delete("/{adventure_id}", status_code=204)
def delete_adventure(adventure_id: str, user_id: str = Depends(current_user_id)):
    """Really delete it. Archiving is the soft option and it is a status.

    gear_usage.adventure_id is ON DELETE SET NULL, deliberately: the run
    happened and the mileage on those shoes is real whether or not the
    adventure it belonged to still exists. Deleting a plan must not rewrite
    the history of the gear.
    """
    db = get_db()
    owned_adventure(db, adventure_id, user_id, writing=True)
    db.table("adventures").delete().eq("id", adventure_id).execute()


@router.get("/{adventure_id}/schema")
def adventure_schema(adventure_id: str, user_id: str = Depends(current_user_id)):
    """The field specs for THIS adventure's activity, so the edit form can be
    built without the client having to know which activity it is looking at."""
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id)
    schema = ACTIVITIES.get(adventure["activity_key"])
    if schema is None:
        raise HTTPException(404, "Unknown activity")
    return schema
