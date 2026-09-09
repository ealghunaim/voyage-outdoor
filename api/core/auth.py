"""Auth dependency.

The app sends `Authorization: Bearer <supabase access token>`. We verify by
asking Supabase's own auth service — correct under any signing-key scheme, and
a small TTL cache keeps it cheap. First sight of a user provisions their
profiles row, which every other table's FK depends on.

The DEV_USER_ID fallback survives ONLY when ENV=local and no Bearer is
presented. Flipping ENV=production on the server retires it.
"""
from __future__ import annotations

import time

import httpx
from fastapi import Header, HTTPException

from api.core.config import settings

_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL_S = 300.0
_CACHE_MAX = 500


def _verify(token: str) -> tuple[str, str | None, str | None] | None:
    """Token → (user_id, email, name), or None. Fresh client per call."""
    try:
        with httpx.Client(timeout=8) as c:
            r = c.get(
                f"{settings.supabase_url}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}",
                         "apikey": settings.supabase_service_key},
            )
        if r.status_code != 200:
            return None
        body = r.json()
        uid = body.get("id")
        if not uid:
            return None
        meta = body.get("user_metadata") or {}
        return (uid, body.get("email"), meta.get("name") or meta.get("full_name"))
    except Exception as e:                                    # noqa: BLE001
        print(f"[auth] verify failed: {type(e).__name__}: {e}")
        return None


def _ensure_profile(user_id: str, email: str | None, name: str | None) -> None:
    """Idempotent: every authenticated user has a profiles row (FK target).

    Only non-empty values are written. Upserting None over a name somebody set
    elsewhere is how an upsert quietly becomes a delete.
    """
    try:
        from api.core.db import get_db
        row: dict = {"id": user_id}
        if email:
            row["email"] = email
        if name:
            row["name"] = name
        db = get_db()
        db.table("profiles").upsert(row).execute()
        # Preferences are created alongside rather than lazily. Every read of
        # them would otherwise need a "or defaults" branch, and those branches
        # disagree with each other over time.
        db.table("user_preferences").upsert(
            {"user_id": user_id}, on_conflict="user_id",
            ignore_duplicates=True).execute()
    except Exception as e:                                    # noqa: BLE001
        print(f"[auth] profile ensure failed: {type(e).__name__}: {e}")


def current_user_id(authorization: str | None = Header(default=None)) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        now = time.time()
        hit = _cache.get(token)
        if hit and hit[1] > now:
            return hit[0]
        verified = _verify(token)
        if verified:
            uid = verified[0]
            if len(_cache) > _CACHE_MAX:
                _cache.clear()
            _cache[token] = (uid, now + _CACHE_TTL_S)
            _ensure_profile(uid, verified[1], verified[2])
            return uid
        raise HTTPException(401, "Invalid or expired session — sign in again.")

    if settings.env == "local" and settings.dev_user_id:
        return settings.dev_user_id
    raise HTTPException(401, "Sign in required.")
