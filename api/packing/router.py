"""The pack: generate it, work through it, check readiness (§8, §9)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.core.access import owned_adventure
from api.core.auth import current_user_id
from api.core.db import get_db
from api.engines import pack as engine
from api.packing import service

router = APIRouter(prefix="/v1/adventures", tags=["pack"])

#: What a person can do to an item (§9). The optional four exist for after the
#: race; the app only offers the first four in Phase 3.
STATES = ("not_selected", "selected", "packed", "verified",
          "in_use", "returned", "missing", "damaged")


class StatePatch(BaseModel):
    state: str = Field(min_length=1)


class ItemAdd(BaseModel):
    """Adding something the engine did not think of.

    Source is stamped `manual`, so a later regeneration can tell it apart from
    a rule's output and — importantly — so nobody can mistake it for something
    the engine decided.
    """
    name: str = Field(min_length=1, max_length=120)
    category_key: str | None = None
    gear_item_id: str | None = None
    critical: bool = False


@router.post("/{adventure_id}/pack", status_code=201)
def generate_pack(adventure_id: str, user_id: str = Depends(current_user_id)):
    """Run the engines and store the result.

    Regenerating is safe: pack states you have already set are carried over.
    A regeneration that un-packed a packed bag would be one nobody ever runs
    twice, and they would then race off a stale list.
    """
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id, writing=True)
    return service.generate(db, adventure, user_id)


@router.get("/{adventure_id}/pack")
def get_pack(adventure_id: str, user_id: str = Depends(current_user_id)):
    """The stored pack. Does NOT generate one.

    A GET that silently generates would hide how expensive generation is and
    would rewrite the list — including its states — every time a screen
    mounted. `list: null` is the honest answer before one exists.
    """
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id)
    return service.read(db, adventure)


def _owned_item(db, adventure_id: str, item_id: str, user_id: str) -> dict:
    owned_adventure(db, adventure_id, user_id, writing=True)
    rows = (db.table("packing_list_items").select("*, packing_lists(adventure_id)")
            .eq("id", item_id).limit(1).execute().data)
    if not rows or (rows[0].get("packing_lists") or {}).get("adventure_id") != adventure_id:
        raise HTTPException(404, "Not on this pack list")
    return rows[0]


@router.patch("/{adventure_id}/pack/items/{item_id}")
def set_item_state(adventure_id: str, item_id: str, body: StatePatch,
                   user_id: str = Depends(current_user_id)):
    """Move one item through the pack states.

    ANY state to any state, deliberately — unlike the adventure status machine.
    Packing is not a workflow: things come back out of a bag, get swapped, get
    found broken at the last minute. A transition table here would be a rule
    about the physical world that the physical world does not follow.
    """
    db = get_db()
    if body.state not in STATES:
        raise HTTPException(422, f"state must be one of {', '.join(STATES)}")
    _owned_item(db, adventure_id, item_id, user_id)
    rows = (db.table("packing_list_items").update({"state": body.state})
            .eq("id", item_id).execute().data)
    return rows[0] if rows else {}


@router.post("/{adventure_id}/pack/items", status_code=201)
def add_item(adventure_id: str, body: ItemAdd,
             user_id: str = Depends(current_user_id)):
    """Add a line the engine did not produce.

    Classified OPTIONAL rather than REQUIRED: the readiness figure counts
    required items, and letting a hand-added line raise the bar would mean the
    number measured the list rather than the plan.
    """
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id, writing=True)
    stored = service.read(db, adventure)
    if not stored["list"]:
        raise HTTPException(409, "Generate a pack for this adventure first.")
    if body.gear_item_id:
        from api.core.access import owned_gear
        owned_gear(db, body.gear_item_id, user_id)
    return db.table("packing_list_items").insert({
        "list_id": stored["list"]["id"],
        "gear_item_id": body.gear_item_id,
        "name": body.name.strip(),
        "category_key": body.category_key,
        "classification": engine.OPTIONAL,
        "critical": body.critical,
        "rule_key": "manual",
        "reason": "Added by you.",
        "source": "manual",
        "sort": 9999,
    }).execute().data[0]


@router.delete("/{adventure_id}/pack/items/{item_id}", status_code=204)
def remove_item(adventure_id: str, item_id: str,
                user_id: str = Depends(current_user_id)):
    """Remove a line.

    Regenerating brings back anything a rule still argues for, which is the
    right behaviour: this removes it from THIS list, not from the rules.
    """
    db = get_db()
    _owned_item(db, adventure_id, item_id, user_id)
    db.table("packing_list_items").delete().eq("id", item_id).execute()


@router.get("/{adventure_id}/readiness")
def get_readiness(adventure_id: str, user_id: str = Depends(current_user_id)):
    """The departure check (§9), on its own so a card can poll it cheaply."""
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id)
    return service.read(db, adventure)["readiness"]
