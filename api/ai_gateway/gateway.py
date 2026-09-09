"""AI gateway — the ONE place model calls happen.

Forked from VoyageOS, where the shape was earned rather than designed. Routing,
ceilings and prices live here; call sites name a TASK and get an answer.

NOTHING CALLS THIS UNTIL PHASE 4. It is here from the first commit because
`ai_runs` is only useful with a baseline: the number that decides whether the
daily cap is right — what a Smart Pack narrative over a full gear locker
actually costs — cannot be measured retroactively.

THE BOUNDARY THIS FILE SITS ON: every engine decision is made before a call
reaches here. The gateway carries explanations, never verdicts. See AGENTS.md.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import HTTPException

from api.core.config import settings

#: task → tier. The one-line model switch (§0.6).
#:
#: The pattern inherited from VoyageOS's guide engine is "cheap tier for the
#: fast first paint, stronger tier for depth". It applies here only where the
#: two halves are genuinely independent — which for Smart Pack they are NOT,
#: because the REQUIRED classification is what MISSING is computed against. So
#: Smart Pack is one deterministic pass and one narrative call, and the tiering
#: below reflects that rather than copying a shape that does not fit.
TASK_ROUTE = {
    "pack_narrative":     "mid",       # writes the readiness paragraph over engine output
    "gear_match_explain": "small",     # one sentence per ranked item
    "compat_explain":     "small",     # why a rule fired, in plain language
    "health_explain":     "small",     # why a threshold is close
    "ask_outdoor":        "small",     # the assistant, grounded in locker + adventure
    "ask_outdoor_deep":   "mid",       # follow-ups that need the whole locker in context
    "pack_narrative_complex": "frontier",   # multi-day, multi-discipline; unused in V1
}

#: Output ceilings per task, ~2x expected peak. Unused ceiling is free —
#: billing follows tokens produced, not the cap — and a ceiling that is too low
#: surfaces as a JSON parse error that reads like the model's fault. VoyageOS
#: hid a 50% failure rate that way for weeks.
#:
#: THESE ARE GUESSES until Phase 4 measures them. The comment stays until the
#: numbers are real; a guess labelled as a guess is honest, a guess that looks
#: like a measurement is not.
TASK_MAX_TOKENS = {
    "pack_narrative": 3000,
    "pack_narrative_complex": 6000,
    "ask_outdoor": 1000,
    "ask_outdoor_deep": 3000,
    "gear_match_explain": 1200,
    "compat_explain": 600,
    "health_explain": 600,
}

DEFAULT_MAX_TOKENS = 2000

#: USD per million tokens (input, output).
TIER_PRICES = {
    "small": (1.0, 5.0),      # claude-haiku-4-5
    "mid": (2.0, 10.0),       # claude-sonnet-5
    "frontier": (5.0, 25.0),  # claude-opus-5
}


@dataclass
class AiResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    #: Why the model stopped. "max_tokens" means the text is cut off mid-
    #: sentence and any JSON in it is invalid — a LENGTH problem, not a
    #: formatting one, and retrying it unchanged fails identically.
    stop_reason: str = ""

    @property
    def truncated(self) -> bool:
        return self.stop_reason == "max_tokens"


def _tier(task: str) -> str:
    return TASK_ROUTE.get(task, "small")


def _model_for(tier: str) -> str:
    return {"small": settings.model_small,
            "mid": settings.model_mid,
            "frontier": settings.model_frontier}[tier]


@lru_cache
def _client():
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY missing from .env — add it and restart.")
    from anthropic import Anthropic
    return Anthropic(api_key=settings.llm_api_key)


def check_budget(db, user_id: str) -> None:
    """Per-user daily cost cap. Raises 429 when exhausted."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    rows = (db.table("ai_runs").select("cost_usd")
            .eq("user_id", user_id).gte("created_at", today).execute()).data
    spent = sum(float(r["cost_usd"] or 0) for r in rows)
    if spent >= settings.ai_daily_cost_cap_usd:
        raise HTTPException(
            429,
            f"Daily AI budget reached (${spent:.2f} of "
            f"${settings.ai_daily_cost_cap_usd:.2f}). Resets at midnight UTC.",
        )


def complete(task: str, system: str, user_content: str, *,
             db=None, user_id: str | None = None,
             max_tokens: int | None = None) -> AiResult:
    tier = _tier(task)
    model = _model_for(tier)
    in_price, out_price = TIER_PRICES[tier]
    if max_tokens is None:
        max_tokens = TASK_MAX_TOKENS.get(task, DEFAULT_MAX_TOKENS)

    t0 = time.monotonic()
    # Prompt caching: long static system prompts bill repeat reads at ~10% and
    # return faster. Short ones skip the flag — below the API's cacheable
    # minimum, marking them does nothing but add a field.
    system_payload = (
        [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if len(system) >= 4000 else system
    )

    resp = None
    for attempt in range(2):
        try:
            resp = _client().messages.create(
                model=model, max_tokens=max_tokens,
                system=system_payload,
                messages=[{"role": "user", "content": user_content}],
            )
            break
        except HTTPException:
            raise
        except Exception as e:                                # noqa: BLE001
            if attempt == 0:
                print(f"[ai] {task} transient {type(e).__name__} — retrying once")
                time.sleep(1.0)
                continue
            print(f"[ai] {task} model call failed: {type(e).__name__}: {e}")
            raise HTTPException(502, "The AI service is busy right now — try again in a moment.")

    latency_ms = int((time.monotonic() - t0) * 1000)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    stop = getattr(resp, "stop_reason", "") or ""
    tin, tout = resp.usage.input_tokens, resp.usage.output_tokens

    if stop == "max_tokens":
        print(f"[ai] {task} TRUNCATED at max_tokens={max_tokens} "
              f"({tout} out) — raise the ceiling for this task")
    cread = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
    cwrite = getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
    if cread or cwrite:
        print(f"[ai] cache {task}: read {cread} · wrote {cwrite}")

    cost = round(tin * in_price / 1e6 + tout * out_price / 1e6, 5)

    if db is not None:
        # Observability must never take the feature down with it: the call has
        # already succeeded and the user is owed its result.
        try:
            db.table("ai_runs").insert({
                "user_id": user_id, "task": task, "provider": "anthropic",
                "model": model, "tokens_in": tin, "tokens_out": tout,
                "cost_usd": cost, "latency_ms": latency_ms, "stop_reason": stop,
            }).execute()
        except Exception as e:                                # noqa: BLE001
            print(f"[ai] ai_runs log failed ({type(e).__name__}) — "
                  f"{task} cost ${cost} went unrecorded")

    return AiResult(text=text, model=model, tokens_in=tin, tokens_out=tout,
                    cost_usd=cost, latency_ms=latency_ms, stop_reason=stop)
