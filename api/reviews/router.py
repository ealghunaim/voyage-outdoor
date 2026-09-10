"""Reviews of gear you own (§14, §15).

WHY REVIEWS ATTACH TO A LOCKER ITEM. §0.4 leaves the product catalog thin and
admin-entered in V1, so reviews of catalog products would be a feature with
almost nothing to point at. Reviews of your own gear have their evidence
already: the usage log, the maintenance history, and the adventures the thing
was carried on.

THE CONTEXT IS THE FEATURE. A rating on its own is the least interesting part —
"four stars" tells you nothing about whether that was after one wet weekend or
two seasons. So every review is stored with a snapshot of what the record said
at the moment it was written, and the screen shows it: 340 km, 12 sessions, two
adventures, condition band at the time. §15 asks for "contextual reviews", and
this is the context.

Snapshotted rather than joined, deliberately. A live join would let a review
written at 200 km silently start claiming 900, which is a review rewriting
itself without its author touching it.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.core.access import owned_gear
from api.core.auth import current_user_id
from api.core.db import get_db
from api.engines import gear_health

router = APIRouter(prefix="/v1", tags=["reviews"])

#: Same guard as the gear router: a malformed id must not reach PostgREST,
#: where it returns a 500 that reads like the server broke.
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: str | None = Field(default=None, max_length=4000)


def _context(db, gear: dict) -> dict:
    """What the record said at the moment of writing."""
    usage = (db.table("gear_usage")
             .select("distance_m,duration_s,occurred_on,adventure_id")
             .eq("gear_item_id", gear["id"]).execute().data)

    totals = {"distance_m": 0, "duration_s": 0, "sessions": len(usage)}
    for row in usage:
        totals["distance_m"] += row.get("distance_m") or 0
        totals["duration_s"] += row.get("duration_s") or 0

    adventure_ids = sorted({r["adventure_id"] for r in usage if r.get("adventure_id")})
    adventures = []
    if adventure_ids:
        adventures = [a["title"] for a in
                      (db.table("adventures").select("title")
                       .in_("id", adventure_ids).execute().data)]

    health = gear_health.evaluate(gear, totals)
    maintenance = (db.table("maintenance_events").select("id")
                   .eq("gear_item_id", gear["id"]).execute().data)

    return {
        **totals,
        "adventures": adventures,
        "maintenance_events": len(maintenance),
        "condition_pct": health.condition_pct,
        "health_state": health.state,
        # The engine's own sentence, band and all. A review that said "worn out"
        # where the engine said "640-960 km, worth a look" would be the review
        # inventing a certainty the data does not carry (§12).
        "health_message": health.message,
        "health_ruleset": health.ruleset,
        "owned_since": gear.get("purchase_date"),
    }


@router.get("/gear/{gear_id}/review")
def get_review(gear_id: str, user_id: str = Depends(current_user_id)):
    """This user's review of this item, or null. Never 404s on absence —
    "you have not reviewed this" is an ordinary state, not an error."""
    db = get_db()
    owned_gear(db, gear_id, user_id)
    rows = (db.table("gear_reviews").select("*")
            .eq("gear_item_id", gear_id).eq("user_id", user_id)
            .limit(1).execute().data)
    return rows[0] if rows else None


@router.put("/gear/{gear_id}/review")
def upsert_review(gear_id: str, body: ReviewIn,
                  user_id: str = Depends(current_user_id)):
    """Write or rewrite the review. PUT rather than POST: there is exactly one
    per person per item, so writing twice is an edit and the verb should say
    so."""
    db = get_db()
    gear = owned_gear(db, gear_id, user_id, writing=True)

    row = {
        "user_id": user_id,
        "gear_item_id": gear_id,
        # Copied, not joined — see the migration on why unlinking an item later
        # must not delete its review from a product's average.
        "product_id": gear.get("product_id"),
        "rating": body.rating,
        "body": (body.body or "").strip() or None,
        "context": _context(db, gear),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    saved = (db.table("gear_reviews")
             .upsert(row, on_conflict="user_id,gear_item_id")
             .execute().data)
    return saved[0] if saved else row


@router.delete("/gear/{gear_id}/review", status_code=204)
def delete_review(gear_id: str, user_id: str = Depends(current_user_id)):
    db = get_db()
    owned_gear(db, gear_id, user_id, writing=True)
    db.table("gear_reviews").delete() \
      .eq("gear_item_id", gear_id).eq("user_id", user_id).execute()


@router.get("/reviews")
def list_reviews(user_id: str = Depends(current_user_id)):
    """Everything this user has reviewed, newest first.

    Joined to the gear so a list screen can render without a second round trip
    per row — and left as a join rather than denormalised onto the review,
    because an item's NAME is allowed to change and the review should follow it.
    Only the measured context is frozen.
    """
    db = get_db()
    rows = (db.table("gear_reviews")
            .select("*, gear_items(name,brand,category_key,status)")
            .eq("user_id", user_id).order("updated_at", desc=True)
            .limit(100).execute().data)
    return rows


@router.get("/products/{product_id}/reviews")
def product_reviews(product_id: str, user_id: str = Depends(current_user_id)):
    """Reviews of one catalog product.

    IN V1 THIS RETURNS YOUR OWN REVIEWS AND USUALLY NOTHING, because §0.4 keeps
    the catalog thin and locker items are rarely linked to it. The endpoint
    exists now so the aggregation has a shape to grow into rather than being
    retrofitted later — and it returns an honest empty list meanwhile, with a
    count, so a screen can say "no reviews yet" rather than looking broken.

    Scoped to the caller: there is no community in V1 (§27 puts it at Phase 7),
    and exposing other people's reviews through an endpoint written before
    anyone decided what a public review looks like would be a privacy decision
    made by accident.
    """
    # Guarded BEFORE the connection, matching the gear router: the tests there
    # assert a malformed id never reaches the database at all.
    if not _UUID.match(product_id):
        raise HTTPException(422, "That is not a product id.")
    db = get_db()
    rows = (db.table("gear_reviews").select("rating,body,context,updated_at")
            .eq("product_id", product_id).eq("user_id", user_id)
            .order("updated_at", desc=True).limit(50).execute().data)
    ratings = [r["rating"] for r in rows]
    return {
        "reviews": rows,
        "count": len(rows),
        # None, not 0. An average of nothing is not zero stars.
        "average": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "scope": "your own reviews only — there is no community yet",
    }
