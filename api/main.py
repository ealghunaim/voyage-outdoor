"""Voyage Outdoor API — Phase 4: the AI layer over everything Phases 1-3 decide.

WHAT PHASE 4 ADDED, AND WHAT IT DELIBERATELY DID NOT. The narrative, the
explanations and Ask Outdoor read engine output and write prose. The race-kit
importer reads a race page and writes a DRAFT. Nothing a model produces reaches
a classification, a warning, a readiness figure or `products.specs`, and the
import graph is what enforces it: api/engines/* does not import api/ai/* or
api/racekit/*, so no model output can reach a decision without a human first
accepting it (§0.5, §11, §12, §24).

Turn the AI off entirely — no key, budget spent, Anthropic down — and the app
loses its paragraphs and keeps its pack.

NO BACKGROUND SCHEDULER YET, and that is a decision rather than an omission.
VoyageOS runs its notification governor and weather job with APScheduler inside
the web process, which means it cannot run a second web instance without both
jobs running twice — `max_instances=1` is per-process, not per-service. Phase 2
needs a weather tick; when it lands, it goes in a Render cron job or a separate
worker service, not in here. Audit risk #3.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.activities.router import router as activities_router
from api.adventures.router import router as adventures_router
from api.ai.router import router as ai_router
from api.core.config import settings
from api.discover.router import router as discover_router
from api.gear.router import router as gear_router
from api.me.router import router as me_router
from api.packing.router import router as pack_router
from api.racekit.router import router as racekit_router
from api.reviews.router import router as reviews_router
from api.weather.router import router as weather_router

app = FastAPI(title="Voyage Outdoor API", version="0.5.0")

#: Paths that do not carry x-voyage-key.
OPEN_PATHS = ("/health", "/docs", "/openapi.json", "/redoc")


@app.middleware("http")
async def shared_secret_guard(request: Request, call_next):
    """The coarse gate. Accepts the current key OR the previous one.

    Rotating a single value 401s every user still on the old build — not
    degraded, unable to reach the API at all — and store updates are neither
    instant nor universal. So a rotation overlaps, exactly the way a migration
    does: old and new both work until the old is retired, and retiring it is a
    separate, later decision.

    An EMPTY previous key contributes nothing: it is filtered out rather than
    compared, so a blank env var cannot become a second door. With no key
    configured at all the gate is off, which is the local-development state.
    """
    accepted = {k for k in (settings.app_shared_secret,
                            settings.app_shared_secret_previous) if k}
    if accepted and request.url.path not in OPEN_PATHS:
        if request.headers.get("x-voyage-key") not in accepted:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


for r in (me_router, activities_router, gear_router, adventures_router,
          weather_router, pack_router, ai_router, racekit_router,
          discover_router, reviews_router):
    app.include_router(r)


@app.get("/health")
def health():
    # `ai` reports whether a key is configured, not whether the last call
    # worked. The app uses it to decide whether to offer the buttons at all —
    # a "Explain this pack" button that always 503s is worse than no button.
    return {"ok": True, "version": "0.5.0", "phase": 5,
            "ai": bool(settings.llm_api_key)}
