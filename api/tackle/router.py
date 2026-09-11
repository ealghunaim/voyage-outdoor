"""Tackle setups (§11, Phase 7) — the gear↔gear compatibility surface.

A SEPARATE ENDPOINT BECAUSE IT IS A SEPARATE QUESTION. `/v1/adventures/{id}/pack`
answers "what do I take". This answers "does what I take work together", which
for fishing is the question that breaks tackle. Trail running never needed it:
nothing in a pack list is incompatible with anything else in it.

NOTHING IS STORED. Setups are built from the locker on every request and thrown
away — see engines/tackle.build_setups. There is no `setups` table because
nothing yet needs one, and a table is far harder to remove than to add.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.core.access import owned_adventure
from api.core.auth import current_user_id
from api.core.db import get_db
from api.engines import tackle

router = APIRouter(prefix="/v1", tags=["tackle"])


def _render(setup: dict, verdicts: list) -> dict:
    return {
        "rod": _brief(setup.get("rod")),
        "parts": {role: _brief(setup.get(role)) for role in tackle.ROLES
                  if setup.get(role)},
        "verdicts": [
            {"rule_key": v.rule_key, "state": v.state, "message": v.message,
             "roles": list(v.roles), "ruleset": v.ruleset, "detail": v.detail}
            for v in verdicts
        ],
        # Counted here rather than on the client so two screens cannot disagree
        # about whether a setup is "fine".
        "problems": sum(1 for v in verdicts if v.is_problem),
        "unknowns": sum(1 for v in verdicts if v.state == "unknown"),
    }


def _brief(item: dict | None) -> dict | None:
    if not item:
        return None
    return {"id": item["id"], "name": item.get("name"),
            "category_key": item.get("category_key"),
            "attributes": item.get("attributes") or {}}


@router.get("/tackle/setups")
def locker_setups(user_id: str = Depends(current_user_id)):
    """Every rod in the locker with the rest of the kit it implies.

    No adventure, so no technique rule — this is "does my tackle agree with
    itself", not "is it right for Thursday".
    """
    db = get_db()
    locker = (db.table("gear_items").select("*")
              .eq("user_id", user_id).eq("status", "active").execute().data)
    setups = tackle.build_setups(locker)
    return {
        "ruleset": tackle.TACKLE_RULESET,
        "setups": [_render(s, tackle.evaluate_setup(s)) for s in setups],
        # Said out loud: an empty answer here means no rods, not no problems.
        "note": ("Built from the rods in your locker. Nothing is saved — these "
                 "are worked out fresh each time."),
    }


@router.get("/adventures/{adventure_id}/tackle")
def adventure_setups(adventure_id: str, user_id: str = Depends(current_user_id)):
    """The same, judged against what the trip is actually doing.

    Adds the one rule that reaches both the gear and the adventure: a jigging
    rod on a popping trip is a question about the pair.
    """
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id)
    if adventure.get("activity_key") != "fishing":
        # A 409 rather than an empty list. "No setups" and "this is a running
        # race" are different answers, and an empty list would read as the first.
        raise HTTPException(
            409,
            f"Tackle setups are a fishing thing; this adventure is "
            f"{adventure.get('activity_key')}.")

    locker = (db.table("gear_items").select("*")
              .eq("user_id", user_id).eq("status", "active").execute().data)
    setups = tackle.build_setups(locker)
    return {
        "ruleset": tackle.TACKLE_RULESET,
        "adventure": {"id": adventure["id"], "title": adventure.get("title")},
        "setups": [_render(s, tackle.evaluate_setup(s, adventure)) for s in setups],
        "note": ("Thresholds here are standard tackle practice, assumed rather "
                 "than measured — correct anything that is wrong for your gear."),
    }
