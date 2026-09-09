"""The Gear Locker (Master Prompt §5, §6).

A permanent inventory of what one person owns. Not a packing list, and not a
product database — those are different things that this one feeds.

MANUAL ENTRY IS THE PRIMARY PATH, not a fallback. There is no live product
database in V1 (§0.4), so every route here works with `product_id` null and
nothing degrades. The product link is an optimisation for later, which is why
it is nullable rather than required-with-a-placeholder.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.activities.validate import validate_gear_attributes
from api.core.access import owned_gear, owned_gear_child
from api.core.auth import current_user_id
from api.core.db import get_db

router = APIRouter(prefix="/v1/gear", tags=["gear"])

STATUSES = ("active", "retired", "lost", "damaged")


class GearCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    category_key: str | None = None
    activity_key: str | None = None
    size: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=40)
    weight_g: int | None = Field(default=None, ge=0, le=100_000)
    purchase_date: date | None = None
    purchase_price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    serial_number: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    attributes: dict | None = None
    product_id: str | None = None
    variant_id: str | None = None


class GearPatch(BaseModel):
    """Every field optional. Absent means "leave alone"; null means "clear".

    Pydantic cannot express that distinction on its own — both arrive as None —
    so the route reads `model_dump(exclude_unset=True)` and the difference is
    carried by whether the key is present at all.
    """
    name: str | None = Field(default=None, min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    category_key: str | None = None
    activity_key: str | None = None
    size: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=40)
    weight_g: int | None = Field(default=None, ge=0, le=100_000)
    purchase_date: date | None = None
    purchase_price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    serial_number: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    favorite: bool | None = None
    status: str | None = None
    tags: list[str] | None = None
    attributes: dict | None = None


class UsageIn(BaseModel):
    occurred_on: date
    adventure_id: str | None = None
    distance_m: int | None = Field(default=None, ge=0, le=1_000_000)
    duration_s: int | None = Field(default=None, ge=0, le=1_000_000)
    conditions: dict = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=1000)


class MaintenanceIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    occurred_on: date
    notes: str | None = Field(default=None, max_length=1000)
    cost_cents: int | None = Field(default=None, ge=0)
    next_due_on: date | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(payload: dict) -> dict:
    """dates → ISO strings. supabase-py serialises with the stdlib json encoder,
    which does not know what a datetime.date is, and the failure is a 500 from
    inside the client rather than anything that names the field."""
    return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
            for k, v in payload.items()}


# ── the locker ──────────────────────────────────────────────────────────────

@router.get("")
def list_gear(status: str | None = None,
              activity_key: str | None = None,
              category_key: str | None = None,
              favorite: bool | None = None,
              q: str | None = Query(default=None, max_length=80),
              user_id: str = Depends(current_user_id)):
    """The locker list.

    Defaults to ACTIVE only. A locker that shows retired shoes beside current
    ones by default answers "what do I own" with "everything I have ever owned",
    which is a different and much less useful question. `status=all` opts in.
    """
    db = get_db()
    query = db.table("gear_items").select("*").eq("user_id", user_id)
    if status == "all":
        pass
    elif status:
        if status not in STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(STATUSES)} or 'all'")
        query = query.eq("status", status)
    else:
        query = query.eq("status", "active")
    if activity_key:
        query = query.eq("activity_key", activity_key)
    if category_key:
        query = query.eq("category_key", category_key)
    if favorite is not None:
        query = query.eq("favorite", favorite)
    if q:
        # ilike over name only. Brand and model are usually IN the name for a
        # manually entered item ("Norda 005"), and a three-column or-filter
        # returns the same rows twice as often as it returns extra ones.
        query = query.ilike("name", f"%{q}%")
    return query.order("favorite", desc=True).order("created_at", desc=True).execute().data


@router.post("", status_code=201)
def create_gear(body: GearCreate, user_id: str = Depends(current_user_id)):
    db = get_db()
    payload = _jsonable(body.model_dump(exclude={"attributes"}))
    payload["user_id"] = user_id
    payload["attributes"] = validate_gear_attributes(
        body.activity_key, body.category_key, body.attributes)
    return db.table("gear_items").insert(payload).execute().data[0]


@router.get("/{gear_id}")
def get_gear(gear_id: str, user_id: str = Depends(current_user_id)):
    """One item, with its usage rollup.

    The rollup is summed in Python rather than by the database. PostgREST can
    aggregate, but it needs a view or an RPC to do it, and at locker scale — a
    few hundred usage rows for a well-used pair of shoes — the round trip costs
    more than the arithmetic. Revisit if a single item ever carries thousands.
    """
    db = get_db()
    item = owned_gear(db, gear_id, user_id)
    usage = db.table("gear_usage").select("*") \
        .eq("gear_item_id", gear_id).order("occurred_on", desc=True).execute().data
    maintenance = db.table("maintenance_events").select("*") \
        .eq("gear_item_id", gear_id).order("occurred_on", desc=True).execute().data

    item["usage"] = usage
    item["maintenance"] = maintenance
    item["totals"] = {
        "sessions": len(usage),
        "distance_m": sum(u["distance_m"] or 0 for u in usage),
        "duration_s": sum(u["duration_s"] or 0 for u in usage),
        "last_used_on": usage[0]["occurred_on"] if usage else None,
    }
    # condition_pct stays whatever is on the row — null until Phase 3 builds
    # the gear-health engine. It is deliberately NOT guessed from the totals
    # here: a number invented at read time is a number nobody can reproduce,
    # and §12 is explicit that uncertain estimates must not read as facts.
    return item


@router.patch("/{gear_id}")
def update_gear(gear_id: str, body: GearPatch, user_id: str = Depends(current_user_id)):
    db = get_db()
    item = owned_gear(db, gear_id, user_id, writing=True)
    patch = body.model_dump(exclude_unset=True)

    if "status" in patch and patch["status"] not in STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(STATUSES)}")

    if "attributes" in patch:
        # Validated against the category the item WILL have, not the one it has
        # now — a PATCH that moves a headlamp into the shoes category and sets a
        # stack height in the same request must be judged as a whole.
        activity = patch.get("activity_key", item.get("activity_key"))
        category = patch.get("category_key", item.get("category_key"))
        incoming = validate_gear_attributes(activity, category, patch["attributes"],
                                            partial=True)
        # MERGED, not replaced. A PATCH sending one field must not silently
        # delete the other nine; explicit nulls have already been stripped by
        # the validator, which is how a field gets cleared.
        merged = {**(item.get("attributes") or {}), **incoming}
        for key, value in (patch["attributes"] or {}).items():
            if value is None:
                merged.pop(key, None)
        patch["attributes"] = merged

    if patch.get("status") == "retired" and not item.get("retired_at"):
        patch["retired_at"] = _now()
    if "status" in patch and patch["status"] != "retired":
        patch["retired_at"] = None

    patch["updated_at"] = _now()
    rows = db.table("gear_items").update(_jsonable(patch)).eq("id", gear_id).execute().data
    return rows[0] if rows else item


@router.delete("/{gear_id}", status_code=204)
def delete_gear(gear_id: str, user_id: str = Depends(current_user_id)):
    """Really delete it.

    Retiring is the soft option and it is a status, right there in PATCH. A
    delete that quietly retires instead would mean nobody can ever remove the
    duplicate they created by mistake, and the locker fills with rows the owner
    has already decided are not theirs. Usage and maintenance cascade.
    """
    db = get_db()
    owned_gear(db, gear_id, user_id, writing=True)
    db.table("gear_items").delete().eq("id", gear_id).execute()


# ── usage & maintenance ─────────────────────────────────────────────────────

@router.post("/{gear_id}/usage", status_code=201)
def log_usage(gear_id: str, body: UsageIn, user_id: str = Depends(current_user_id)):
    db = get_db()
    owned_gear(db, gear_id, user_id, writing=True)
    if body.adventure_id:
        # Checked rather than trusted: an adventure id from another account
        # would otherwise attach this person's usage to a stranger's row.
        from api.core.access import owned_adventure
        owned_adventure(db, body.adventure_id, user_id)
    payload = _jsonable(body.model_dump())
    payload["gear_item_id"] = gear_id
    return db.table("gear_usage").insert(payload).execute().data[0]


@router.delete("/usage/{usage_id}", status_code=204)
def delete_usage(usage_id: str, user_id: str = Depends(current_user_id)):
    db = get_db()
    owned_gear_child(db, "gear_usage", usage_id, user_id)
    db.table("gear_usage").delete().eq("id", usage_id).execute()


@router.post("/{gear_id}/maintenance", status_code=201)
def log_maintenance(gear_id: str, body: MaintenanceIn,
                    user_id: str = Depends(current_user_id)):
    db = get_db()
    owned_gear(db, gear_id, user_id, writing=True)
    payload = _jsonable(body.model_dump())
    payload["gear_item_id"] = gear_id
    return db.table("maintenance_events").insert(payload).execute().data[0]


@router.delete("/maintenance/{event_id}", status_code=204)
def delete_maintenance(event_id: str, user_id: str = Depends(current_user_id)):
    db = get_db()
    owned_gear_child(db, "maintenance_events", event_id, user_id)
    db.table("maintenance_events").delete().eq("id", event_id).execute()
