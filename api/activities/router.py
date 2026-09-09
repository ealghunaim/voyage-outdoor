"""Activity + category reference data.

The app renders gear forms from this rather than hardcoding fields per
category. That is the whole point of the attribute model: adding a field to a
trail shoe is a change to registry.py and a server restart, not an app release.
"""
from fastapi import APIRouter, Depends, HTTPException

from api.activities.registry import ACTIVITIES, BUILT, schema_for
from api.core.auth import current_user_id
from api.core.db import get_db

router = APIRouter(prefix="/v1", tags=["activities"])


@router.get("/activities")
def list_activities(include_unbuilt: bool = False,
                    user_id: str = Depends(current_user_id)):
    """Activities, built ones first.

    `include_unbuilt` exists for the test suite and for a future Phase 7 picker.
    It defaults to false so the app cannot accidentally offer an activity that
    has no screens behind it — a fishing option that leads nowhere is worse than
    no fishing option.
    """
    db = get_db()
    rows = db.table("activities").select("key,name,built,sort") \
        .order("sort").execute().data
    if not include_unbuilt:
        rows = [r for r in rows if r.get("built")]
    return rows


@router.get("/activities/{activity_key}/schema")
def activity_schema(activity_key: str, user_id: str = Depends(current_user_id)):
    """The field specs the app builds its forms from.

    Served from the Python registry, NOT from activities.attribute_schema. The
    database column is a copy for queryability; this is the original, and
    serving the copy would let the two drift without anyone noticing.
    """
    schema = schema_for(activity_key)
    if schema is None:
        raise HTTPException(404, "Unknown activity")
    return schema


@router.get("/gear-categories")
def list_categories(activity_key: str | None = None,
                    user_id: str = Depends(current_user_id)):
    """Categories for an activity, plus the universal ones.

    A headlamp belongs to no activity in particular (activity_key is null) and
    must appear for every one of them — filtering on equality alone would hide
    every universal category, which is most of the safety kit.
    """
    db = get_db()
    rows = db.table("gear_categories") \
        .select("key,name,activity_key,parent_key,sort") \
        .order("sort").execute().data
    if activity_key:
        rows = [r for r in rows
                if r["activity_key"] in (None, activity_key)]
    return rows


@router.get("/activities/_registry")
def registry_dump(user_id: str = Depends(current_user_id)):
    """Every schema, built or not. Diagnostics and the seed script."""
    return {"built": list(BUILT), "schemas": ACTIVITIES}
