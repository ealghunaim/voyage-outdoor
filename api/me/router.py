"""Profile and preferences."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.core.auth import current_user_id
from api.core.db import get_db

router = APIRouter(prefix="/v1/me", tags=["me"])


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    unit_system: str | None = Field(default=None, pattern="^(metric|imperial)$")
    locale: str | None = Field(default=None, max_length=8)


class PrefsPatch(BaseModel):
    distance_unit: str | None = Field(default=None, pattern="^(km|mi)$")
    weight_unit: str | None = Field(default=None, pattern="^(g|oz)$")
    notification_daily_cap: int | None = Field(default=None, ge=1, le=5)
    quiet_hours: dict | None = None


@router.get("")
def get_me(user_id: str = Depends(current_user_id)):
    db = get_db()
    profile = db.table("profiles").select("*").eq("id", user_id).execute().data
    prefs = db.table("user_preferences").select("*").eq("user_id", user_id).execute().data
    # Both rows are created by _ensure_profile on first authenticated request,
    # so an empty list here means the upsert failed rather than that the user is
    # new. Returned as null rather than fabricated defaults: a client that shows
    # invented preferences will write them back and make them real.
    return {"profile": profile[0] if profile else None,
            "preferences": prefs[0] if prefs else None}


@router.patch("")
def patch_profile(body: ProfilePatch, user_id: str = Depends(current_user_id)):
    db = get_db()
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        return get_me(user_id)
    db.table("profiles").update(patch).eq("id", user_id).execute()
    return get_me(user_id)


@router.patch("/preferences")
def patch_prefs(body: PrefsPatch, user_id: str = Depends(current_user_id)):
    db = get_db()
    patch = body.model_dump(exclude_unset=True)
    if patch:
        db.table("user_preferences").update(patch).eq("user_id", user_id).execute()
    return get_me(user_id)
