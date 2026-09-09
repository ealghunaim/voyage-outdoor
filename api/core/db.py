"""Supabase client (server-side, service key).

FRESH CLIENT PER CALL — deliberately not cached, and this is not an oversight
being repeated. A shared singleton's connection pool goes stale on cloud hosts:
idle keep-alives get closed by the far end, which surfaces as httpx.ReadError
errno 11 and intermittent 500s, and the pool is shared across request threads
AND any background job thread. Per-call clients cost about a millisecond and
remove the entire failure class.

Inherited from VoyageOS, where it was learned from the 500s rather than from
the docs.
"""
from supabase import Client, create_client

from api.core.config import settings


def get_db() -> Client:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError(
            "Supabase not configured. Put SUPABASE_URL and SUPABASE_SERVICE_KEY "
            "in .env at the repo root, then restart uvicorn. See .env.example."
        )
    return create_client(settings.supabase_url, settings.supabase_service_key)
