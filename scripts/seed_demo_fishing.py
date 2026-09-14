"""Put a fishing trip and a tackle locker on the demo account.

WHY THIS EXISTS. Phase 7's §0.9 asks for eyes on a running screen, and the
Tackle card renders nothing without fishing gear to render — the demo account
held nine trail-running items and two races. Seeding by hand through the app is
twenty screens of typing that nobody can reproduce or correct later.

THE SPECS HERE ARE PLACEHOLDERS AND THE NAMES SAY SO.
-----------------------------------------------------
Every rod, reel, line and leader below is a plausible shape for a heavy GT and
jigging outfit. None of it is a measurement of anyone's gear, and the reel
example that appears in the brief has not been confirmed as real rather than
illustrative. So nothing is named after a product: "Popping rod 8 ft PE6-10" is
a description of a rating, which is the honest thing to put on screen while the
real specs are outstanding.

Replace this data the moment the real locker is known. It exists to make the
rules visible, not to stand in for them.

WRITTEN THROUGH THE VALIDATOR, NOT AROUND IT. The rows go in with the service
key because the demo account's password is not recorded anywhere, but every
attribute payload passes through validate_*_attributes first — the same
function api/gear/router.py calls. A seed script that could write attributes the
API would refuse is a seed script that hides schema bugs instead of finding
them.

    PYTHONPATH=. python scripts/seed_demo_fishing.py
    PYTHONPATH=. python scripts/seed_demo_fishing.py --undo
"""
from __future__ import annotations

import sys

from api.activities.validate import (validate_adventure_attributes,
                                     validate_gear_attributes)
from api.core.db import get_db

EMAIL = "demo@voyageoutdoor.test"
TRIP_TITLE = "Abd al Kuri — GT and dogtooth"

#: One rod per outfit, and the rest of the kit each one implies. Deliberately
#: NOT a complete locker: the pack engine should still report the missing
#: categories (tools, terminal tackle, sun protection, safety, first aid) that
#: a remote reef trip requires, because that is the other half of what this
#: screen is for.
GEAR = [
    ("Popping rod 8 ft PE6-10", "rod", {
        "technique": ["popping"], "length_ft": 8.0,
        "pe_min": 6, "pe_max": 10,
        "cast_weight_min_g": 60, "cast_weight_max_g": 150,
        "pieces": 2, "action": "fast"}),
    ("Jigging rod 5 ft 6 PE4-6", "rod", {
        "technique": ["jigging"], "length_ft": 5.6,
        "pe_min": 4, "pe_max": 6, "jig_weight_max_g": 300,
        "pieces": 1, "action": "moderate"}),

    ("Spinning reel 18000, 25 kg drag", "reel", {
        "technique": ["popping"], "size": "18000",
        "size_class": "extra_heavy", "gear_ratio": "5.7:1",
        "drag_kg": 25, "pe_capacity": 8, "sealed": True}),
    # UNDER-RATED ON PURPOSE. PE4 capacity with the PE5 braid below it is the
    # one real mismatch in this locker, so the card has something true to say
    # rather than six green ticks that prove only that it rendered.
    ("Jigging reel 8000, 10 kg drag", "reel", {
        "technique": ["jigging"], "size": "8000",
        "size_class": "medium", "gear_ratio": "6.2:1",
        "drag_kg": 10, "pe_capacity": 4, "sealed": False}),

    ("Braid PE8, 100 lb, 500 m", "line", {
        "kind": "braid", "pe": 8, "lb_test": 100, "metres": 500}),
    ("Braid PE5, 65 lb, 400 m", "line", {
        "kind": "braid", "pe": 5, "lb_test": 65, "metres": 400}),

    ("Fluoro leader 130 lb", "leader", {
        "kind": "fluoro", "lb_test": 130, "metres": 30}),
    ("Fluoro leader 80 lb", "leader", {
        "kind": "fluoro", "lb_test": 80, "metres": 30}),

    ("Popper 150 g", "lure", {
        "technique": ["popping"], "weight_g": 150, "kind": "popper",
        "hook_size": "4/0"}),
    ("Speed jig 250 g", "lure", {
        "technique": ["jigging"], "weight_g": 250, "kind": "jig",
        "hook_size": "7/0"}),
]

TRIP = {
    "title": TRIP_TITLE,
    "activity_key": "fishing",
    "start_date": "2026-11-02",
    "end_date": "2026-11-09",
    "place_name": "Abd al Kuri, Socotra Archipelago",
    # Real coordinates — the weather card needs somewhere to ask about, and
    # this island is the point of the trip.
    "lat": 12.1889,
    "lng": 52.2333,
    "status": "planned",
    "attributes": {
        "trip_type": "liveaboard", "days": 8,
        "technique": ["popping", "jigging"],
        "target_species": ["Giant trevally", "Dogtooth tuna"],
        "water": "reef", "depth_m": 60, "boat_hours": 70,
        "remote": True,
    },
}


def user_id(db) -> str:
    rows = db.table("profiles").select("id,email").eq("email", EMAIL).execute().data
    if not rows:
        print(f"No account for {EMAIL}. Sign in on a device first.")
        sys.exit(1)
    return rows[0]["id"]


def undo(db, uid: str) -> None:
    trips = (db.table("adventures").select("id")
             .eq("user_id", uid).eq("activity_key", "fishing").execute().data)
    for t in trips:
        db.table("adventures").delete().eq("id", t["id"]).execute()
    gear = (db.table("gear_items").select("id")
            .eq("user_id", uid).eq("activity_key", "fishing").execute().data)
    for g in gear:
        db.table("gear_items").delete().eq("id", g["id"]).execute()
    print(f"removed {len(trips)} fishing adventure(s) and {len(gear)} item(s)")


def main() -> None:
    db = get_db()
    uid = user_id(db)
    print(f"{EMAIL} · {uid}\n")

    if "--undo" in sys.argv:
        undo(db, uid)
        return

    # Idempotent, for the same reason the smoke test clears first: a run that
    # half-finished should not leave the next one seeding duplicates.
    undo(db, uid)

    for name, category, attrs in GEAR:
        clean = validate_gear_attributes("fishing", category, attrs)
        db.table("gear_items").insert({
            "user_id": uid, "name": name, "category_key": category,
            "activity_key": "fishing", "status": "active",
            "attributes": clean,
        }).execute()
        print(f"  + {category:<8} {name}")

    clean = validate_adventure_attributes("fishing", TRIP["attributes"])
    trip = db.table("adventures").insert({
        **{k: v for k, v in TRIP.items() if k != "attributes"},
        "user_id": uid, "attributes": clean,
    }).execute().data[0]
    print(f"\n  + adventure  {trip['title']}  {trip['id']}")
    print("\nOpen the trip, then 'Open the pack' — the Tackle card is under "
          "Readiness.\nThe specs above are placeholders (see the docstring).")


if __name__ == "__main__":
    main()
