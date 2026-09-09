"""Weather, and the place lookup that feeds it.

ON DEMAND, NOT ON A SCHEDULE. VoyageOS refreshes weather from an APScheduler
job inside its web process, which is why it can never run a second web
instance — `max_instances=1` is per-process, not per-service. Here the refresh
is a POST the client makes when it opens an adventure, and the snapshots table
is the cache that stops it costing anything on the next read.

When a scheduled sweep is genuinely wanted (a push notification about a storm
the day before a race), it belongs in the cron service already written and
commented in render.yaml — not back inside this process.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from api.core.access import owned_adventure
from api.core.auth import current_user_id
from api.core.db import get_db
from api.weather import provider

router = APIRouter(prefix="/v1", tags=["weather"])

#: How long a stored forecast is treated as current. Providers update roughly
#: hourly; refetching more often spends someone else's rate limit to learn
#: nothing. Callers wanting a guaranteed refetch pass force=true.
FRESH_FOR_SECONDS = 3 * 3600


@router.get("/places")
def search_places(q: str = Query(min_length=2, max_length=80),
                  country_code: str | None = None,
                  user_id: str = Depends(current_user_id)):
    """Place name -> candidates. A list, never a best guess.

    "Chamonix" is unambiguous; "Springfield" is fourteen places on four
    continents. Choosing silently would put an adventure's weather somewhere
    the runner has never been, with nothing on screen looking wrong.
    """
    return provider.geocode(q, country_code)


def _fresh(rows: list[dict]) -> bool:
    if not rows:
        return False
    newest = max((r.get("fetched_at") or "") for r in rows)
    try:
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(newest.replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return False
    return age < FRESH_FOR_SECONDS


@router.post("/adventures/{adventure_id}/weather")
def refresh_weather(adventure_id: str, force: bool = False,
                    user_id: str = Depends(current_user_id)):
    """Fetch and store the forecast for an adventure's dates.

    Answers a REASON rather than an error when there is nothing to fetch. An
    adventure with no coordinates and one that is eleven months out are both
    ordinary states, not failures, and a screen showing "no forecast yet
    — it is 300 days away" is telling the truth in a way a 400 does not.
    """
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id)

    if adventure.get("lat") is None or adventure.get("lng") is None:
        return {"stored": 0, "reason": "no_location",
                "detail": "Add a place to this adventure to get its forecast."}

    existing = (db.table("weather_snapshots").select("*")
                .eq("adventure_id", adventure_id).execute().data)
    if not force and _fresh(existing):
        return {"stored": 0, "reason": "fresh", "days": existing}

    rows = provider.forecast(
        adventure["lat"], adventure["lng"],
        date.fromisoformat(str(adventure["start_date"])),
        date.fromisoformat(str(adventure["end_date"])),
    )
    if not rows:
        beyond = (date.fromisoformat(str(adventure["start_date"])) - date.today()).days
        return {"stored": 0,
                "reason": "beyond_horizon" if beyond > provider.HORIZON_DAYS else "unavailable",
                "detail": (f"That is {beyond} days out — forecasts reach "
                           f"{provider.HORIZON_DAYS} days."
                           if beyond > provider.HORIZON_DAYS
                           else "No provider answered. Try again shortly."),
                "days": existing}

    for row in rows:
        row["adventure_id"] = adventure_id
        row["fetched_at"] = datetime.now(timezone.utc).isoformat()

    # Upserted on the natural key so a refresh REPLACES the day it re-forecasts
    # rather than appending a second opinion. Two rows for one date would make
    # "the forecast" a question of which one a query happened to return first.
    db.table("weather_snapshots").upsert(
        rows, on_conflict="adventure_id,forecast_date,provider").execute()

    stored = (db.table("weather_snapshots").select("*")
              .eq("adventure_id", adventure_id)
              .order("forecast_date").execute().data)
    return {"stored": len(rows), "reason": "fetched",
            "provider": rows[0]["provider"], "days": stored}


@router.get("/adventures/{adventure_id}/weather")
def get_weather(adventure_id: str, user_id: str = Depends(current_user_id)):
    db = get_db()
    owned_adventure(db, adventure_id, user_id)
    return (db.table("weather_snapshots").select("*")
            .eq("adventure_id", adventure_id)
            .order("forecast_date").execute().data)
