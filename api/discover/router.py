"""Discover (§14) — the user's own record, read across adventures.

NO EXTERNAL DATA SOURCE, and that is the phase's defining constraint rather than
an omission. §0.4: no live product database in V1, admin-entered records only,
and a scraper / affiliate API / shopping data provider is "a distinct research
spike for Phase 5, not an assumed dependency". That spike has not been run and
no decision has been made, so nothing here fetches anything. Every row this
endpoint returns already existed in this database before the request arrived.

What it adds is the one thing the app could not do before: reading every
adventure at once. A gap is invisible one pack at a time — "no waterproof
jacket" on the Oman list looks like a fact about Oman until you notice it is
also true of the other three.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.core.auth import current_user_id
from api.core.db import get_db
from api.engines import discover as engine
from api.engines import gear_health
from api.packing import service

router = APIRouter(prefix="/v1", tags=["discover"])

#: How many upcoming adventures to read. Discover is about what is COMING;
#: aggregating a season of finished races would surface gaps that stopped
#: mattering the day the race ended.
HORIZON = 12


@router.get("/discover")
def discover(user_id: str = Depends(current_user_id)):
    """Everything worth knowing that this user's own record already implies."""
    db = get_db()

    adventures = (db.table("adventures").select("*")
                  .eq("user_id", user_id)
                  .in_("status", ["draft", "planned", "active"])
                  .order("start_date").limit(HORIZON).execute().data)

    locker = (db.table("gear_items").select("*")
              .eq("user_id", user_id).eq("status", "active").execute().data)

    # Stored packs only — this endpoint never generates one. A GET that ran the
    # pack engine across a dozen adventures would be a screen that rewrites
    # twelve lists, including their packed states, every time somebody opened a
    # tab. Adventures with no pack yet simply contribute nothing.
    packs = {}
    for adventure in adventures:
        stored = service.read(db, adventure)
        if stored["list"]:
            packs[adventure["id"]] = stored

    attention = _attention(locker)

    # The curated catalog (§0.4) — admin-entered, usually tiny, often empty.
    # Scoped to the categories that are actually short, so a growing catalog
    # never turns this into a general product listing.
    wanted = {i.get("category_key") for pack in packs.values()
              for i in pack["items"]
              if i.get("classification") == "missing" and i.get("category_key")}
    catalog = []
    if wanted:
        catalog = (db.table("products").select("*")
                   .in_("category_key", sorted(wanted))
                   .in_("source", ["manual", "curated"])
                   .limit(50).execute().data)

    result = engine.generate(adventures, packs, locker, attention, catalog)
    return {
        "findings": [f.__dict__ for f in result.findings],
        "snapshot": result.snapshot,
        "ruleset": result.ruleset,
    }


def _attention(locker: list[dict]) -> list[dict]:
    """Gear the health engine flags, recomputed from stored usage.

    Read from the engine rather than from `gear_items.condition_pct` so a
    locker whose health has never been evaluated — nobody has generated a pack
    yet — still reports honestly instead of reporting nothing.
    """
    if not locker:
        return []
    out = []
    for gear in locker:
        detail = gear.get("health_detail") or {}
        state = detail.get("state")
        if state in (gear_health.STATE_INSPECT, gear_health.STATE_PAST):
            out.append({
                "id": gear["id"], "name": gear.get("name"),
                "category_key": gear.get("category_key"),
                "message": detail.get("message"), "state": state,
            })
    return out
