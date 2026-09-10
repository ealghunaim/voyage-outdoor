"""The notification plan (§21). Computed here, scheduled on the device.

WHY THE SPLIT. There is no scheduler on this service — Phase 0 flagged it as
risk #3, because VoyageOS runs its notification governor inside the web process
and therefore cannot run a second web instance without every job firing twice.
Rather than repeat that, the server does the part it is good at (deciding, with
the whole record in front of it, and with a versioned engine somebody can test)
and the device does the part it is good at (firing at six in the evening local
time, with no network, three days from now).

That division also makes the feature work in the place it matters. A reminder
about a race is useful at a trailhead with no signal; anything that needed a
push at delivery time would not arrive.

`today` COMES FROM THE DEVICE. The server does not reliably know where the
runner is standing, and "the evening before" means six o'clock there. Passing
the local date in is the difference between a reminder that survives flying to
the race and one that fires at the wrong end of a day.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from api.core.auth import current_user_id
from api.core.db import get_db
from api.engines import notify
from api.packing import service

router = APIRouter(prefix="/v1", tags=["notifications"])

#: How far ahead to plan. Matches the device's scheduling horizon — iOS caps
#: pending local notifications at 64, and a plan longer than the cap would have
#: its tail silently dropped by the OS rather than by us.
HORIZON = 12


@router.get("/notifications/plan")
def get_plan(today: str | None = Query(default=None,
                                       description="The DEVICE's local date."),
             user_id: str = Depends(current_user_id)):
    db = get_db()

    if today:
        try:
            local_today = date.fromisoformat(today)
        except ValueError:
            raise HTTPException(422, "today must be YYYY-MM-DD.") from None
    else:
        local_today = datetime.now(timezone.utc).date()

    adventures = (db.table("adventures").select("*")
                  .eq("user_id", user_id)
                  .in_("status", ["draft", "planned", "active"])
                  .gte("start_date", local_today.isoformat())
                  .order("start_date").limit(HORIZON).execute().data)

    packs = {}
    for adventure in adventures:
        # Stored only — never generates. A plan request that rebuilt twelve
        # packing lists would rewrite their packed states as a side effect of
        # deciding whether to send a reminder.
        packs[adventure["id"]] = service.read(db, adventure)

    gear = (db.table("gear_items").select("id,name")
            .eq("user_id", user_id).eq("status", "active").execute().data)
    names = {g["id"]: g["name"] for g in gear}
    maintenance = []
    if names:
        rows = (db.table("maintenance_events")
                .select("id,gear_item_id,kind,next_due_on")
                .in_("gear_item_id", list(names)).execute().data)
        maintenance = [{**r, "gear_name": names.get(r["gear_item_id"])}
                       for r in rows if r.get("next_due_on")]

    prefs = (db.table("user_preferences").select("notification_daily_cap")
             .eq("user_id", user_id).limit(1).execute().data)
    cap = (prefs[0].get("notification_daily_cap")
           if prefs else None) or notify.DEFAULT_DAILY_CAP

    planned = notify.plan(adventures, packs, maintenance, local_today,
                          daily_cap=int(cap))
    return {
        "ruleset": notify.NOTIFY_RULESET,
        "today": local_today.isoformat(),
        "daily_cap": int(cap),
        "notifications": [n.__dict__ for n in planned],
        # Stated so a settings screen can explain the quiet rather than leaving
        # someone to conclude the feature is broken. An empty plan is usually
        # the good outcome: everything is packed.
        "note": ("Weather-change and new-release alerts are not part of this "
                 "plan — the first needs a scheduler this service does not run "
                 "yet, the second needs a product catalog V1 does not have."),
    }
