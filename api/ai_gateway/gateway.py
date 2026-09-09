"""AI gateway — the ONE place model calls happen.

Routing, ceilings, prices, budget and logging live here; call sites name a TASK
and get an answer back.

THE BOUNDARY THIS FILE SITS ON (§0.5, §11, §12). Every classification is
decided by an engine before a call reaches here. What crosses this line is
already-decided structure going out and prose coming back. The gateway carries
explanations, never verdicts: nothing downstream of a model call may change a
`required` into a `recommended`, invent a warning, or write to `products.specs`.
The one place a model produces new *facts* rather than new sentences is the
race-kit importer, and there its output lands as a DRAFT a human confirms —
see api/racekit/.

Phase 4 measured what Phases 0–3 could only guess at. Three things were wrong
in the version written before anything ran:

1.  `max_tokens` bounds THINKING PLUS TEXT, and on Opus 5 thinking is on by
    default. The old 600-token ceiling for a one-sentence explanation was not
    tight, it was unreachable — the model would have spent the entire budget
    reasoning and returned an empty string with `stop_reason: max_tokens`. The
    ceilings below are sized for both halves.
2.  A hand-rolled `for attempt in range(2)` retry sat on top of an SDK that
    already retries 429s and 5xx with exponential backoff, so a rate-limited
    request was retried six times, not twice. The SDK owns retries now; this
    file owns the error MAPPING.
3.  Tiering by cost was a decision made before a single output had been read.
    See config.py — every tier resolves to one model and EFFORT is the dial.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

import anthropic
from fastapi import HTTPException

from api.core.config import settings

#: Bump when a system prompt changes. Stored on every ai_outputs row, so a
#: cached narrative written under an older prompt is identifiable — and
#: re-generatable — rather than indistinguishable from a current one.
PROMPT_VERSION = "ai-v1"

#: task → tier. The one-line model switch (§0.6). All three tiers currently
#: resolve to the same model; see config.py for why, and for how to change it
#: without touching code.
TASK_ROUTE = {
    "pack_narrative":     "mid",
    "gear_match_explain": "small",
    "compat_explain":     "small",
    "health_explain":     "small",
    "ask_outdoor":        "small",
    "ask_outdoor_deep":   "mid",
    "race_kit_extract":   "mid",
}

#: task → reasoning effort. THIS is the cost and latency dial.
#:
#: `low` is not a lesser model — it is the same model told to stop deliberating
#: on a task that does not reward deliberation. Rewriting one engine sentence in
#: plain language does not; reading a race manual that buries "waterproof jacket
#: with taped seams, min 10,000mm" inside a table of aid stations does.
#:
#: EXTRACTION IS `medium`, MEASURED RATHER THAN ASSUMED. It shipped as `high` on
#: the reasoning that a race manual is hard to read. Run against the Dragon's
#: Back Race kit page — 12k characters, 39 mandatory items across four
#: conditional groups — the two settings returned the SAME 39 items with the
#: same specifications intact (the 300g minimum on the spare layer, the 1.5L
#: hydration capacity, the full contents of the blister kit) for $0.095 and 25s
#: instead of $0.18 and 57s.
#:
#: Which makes sense in hindsight: the prompt asks the model to TRANSCRIBE, not
#: to decide. High effort bought deliberation about a question that was never
#: open. If a page ever defeats `medium` the extraction's own note field will
#: say so, and this is a one-word change.
TASK_EFFORT = {
    "pack_narrative":     "medium",
    "gear_match_explain": "low",
    "compat_explain":     "low",
    "health_explain":     "low",
    "ask_outdoor":        "low",
    "ask_outdoor_deep":   "medium",
    "race_kit_extract":   "medium",
}
DEFAULT_EFFORT = "low"

#: Output ceilings per task. COVERS THINKING AND TEXT TOGETHER — the model can
#: spend most of this reasoning and still owe us a paragraph, so these are sized
#: several times the visible output, not twice it.
#:
#: Unused ceiling is free: billing follows tokens produced, not the cap. A
#: ceiling that is too low is not — it surfaces as truncated prose, or as a
#: JSON parse error that reads like the model's fault. VoyageOS hid a 50%
#: failure rate that way for weeks.
TASK_MAX_TOKENS = {
    "pack_narrative": 8000,
    "ask_outdoor": 6000,
    "ask_outdoor_deep": 10000,
    "gear_match_explain": 4000,
    "compat_explain": 3000,
    "health_explain": 3000,
    "race_kit_extract": 16000,
}
DEFAULT_MAX_TOKENS = 4000

#: USD per million tokens (input, output), BY MODEL ID rather than by tier.
#: Keyed on the tier, the cost log would silently keep quoting Opus prices the
#: moment someone set MODEL_SMALL to Haiku, and ai_runs would be confidently
#: wrong — which is worse than not logging cost at all.
MODEL_PRICES = {
    "claude-opus-5":     (5.0, 25.0),
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-sonnet-5":   (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
}
#: An unknown model is priced at the most expensive rate we know. Guessing low
#: would let an unpriced model run past the daily cap unnoticed.
FALLBACK_PRICE = (5.0, 25.0)

#: Prompt caching pays for itself from the second call, but only above a
#: minimum cacheable prefix — 512 tokens on Opus 5. Marking a shorter system
#: prompt does nothing except add a field to the request. ~4 chars per token.
CACHEABLE_CHARS = 2000

#: Opus 5's classifiers can decline a request. With this beta the API re-runs it
#: on Anthropic's recommended fallback inside the same call, so we get an answer
#: instead of a refusal. Routed by refusal category, which is why "default"
#: beats naming a model: the right substitute depends on WHY it was declined.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

#: Flipped off permanently for the process the first time the API says this
#: account cannot use the beta. One 400 is a configuration fact, not a transient
#: failure, and re-learning it on every request would cost a wasted round trip
#: per call forever.
_fallback_available = True


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
    #: Set when the model that answered is not the model we asked for, i.e. a
    #: server-side fallback ran. Worth surfacing in logs: it means a request
    #: about running shoes tripped a safety classifier, which is a prompt
    #: problem to go and look at.
    served_by_fallback: bool = False
    parsed: object | None = None
    usage_detail: dict = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        return self.stop_reason == "max_tokens"


def _model_for(task: str) -> str:
    tier = TASK_ROUTE.get(task, "small")
    return {"small": settings.model_small,
            "mid": settings.model_mid,
            "frontier": settings.model_frontier}[tier]


@lru_cache
def _client() -> anthropic.Anthropic:
    if not settings.llm_api_key:
        raise HTTPException(
            503,
            "The AI features are not configured on this server "
            "(LLM_API_KEY is empty). Everything else works without them.",
        )
    # max_retries is the SDK's own exponential backoff over 408/409/429/5xx and
    # connection errors. Two is the default; it is named here so the next person
    # reading this file does not add a retry loop on top of one.
    return anthropic.Anthropic(api_key=settings.llm_api_key, max_retries=2,
                               timeout=120.0)


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
            f"${settings.ai_daily_cost_cap_usd:.2f}). Resets at midnight UTC. "
            f"Your pack, gear and warnings are unaffected — those are computed, "
            f"not generated.",
        )


def _system_payload(system: str):
    if len(system) < CACHEABLE_CHARS:
        return system
    return [{"type": "text", "text": system,
             "cache_control": {"type": "ephemeral"}}]


def _raise_for(task: str, exc: Exception) -> None:
    """Map an SDK exception to something a person on a trailhead can act on.

    Most specific first. A single `except APIStatusError` would collapse "your
    key is wrong" and "try again in a minute" into one message, and the SDK
    defines a class per status precisely so they do not have to be.
    """
    print(f"[ai] {task} failed: {type(exc).__name__}: {exc}")
    if isinstance(exc, anthropic.AuthenticationError):
        raise HTTPException(503, "The AI service rejected this server's key.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        raise HTTPException(503, "This server's AI key cannot use that model.")
    if isinstance(exc, anthropic.NotFoundError):
        raise HTTPException(503, "That AI model is not available to this server.")
    if isinstance(exc, anthropic.RateLimitError):
        raise HTTPException(429, "The AI service is rate-limited right now — "
                                 "try again in a minute.")
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        raise HTTPException(504, "Could not reach the AI service.")
    if isinstance(exc, anthropic.APIStatusError):
        raise HTTPException(502, "The AI service is busy right now — "
                                 "try again in a moment.")
    raise HTTPException(502, "The AI service could not be reached.")


def _account(task: str, model: str, resp, t0: float, db, user_id: str | None):
    latency_ms = int((time.monotonic() - t0) * 1000)
    usage = resp.usage
    tin = usage.input_tokens or 0
    tout = usage.output_tokens or 0
    cread = getattr(usage, "cache_read_input_tokens", 0) or 0
    cwrite = getattr(usage, "cache_creation_input_tokens", 0) or 0

    served = getattr(resp, "model", model) or model
    # PRICED ON THE MODEL THAT ANSWERED, not the one that was asked. After a
    # server-side fallback those are different, and billing follows the former.
    in_price, out_price = MODEL_PRICES.get(served, FALLBACK_PRICE)
    # A cache read bills at ~10% of input, a write at ~1.25x. Ignoring that
    # would over-report cost on every warm call and make the daily cap fire
    # early — a user locked out of explanations they had not actually paid for.
    cost = round((tin * in_price
                  + cread * in_price * 0.1
                  + cwrite * in_price * 1.25
                  + tout * out_price) / 1e6, 5)

    stop = getattr(resp, "stop_reason", "") or ""
    if stop == "max_tokens":
        print(f"[ai] {task} TRUNCATED ({tout} out) — raise TASK_MAX_TOKENS")
    if cread or cwrite:
        print(f"[ai] cache {task}: read {cread} · wrote {cwrite}")
    print(f"[ai] {task} {served} in={tin} out={tout} "
          f"${cost} {latency_ms}ms stop={stop}")

    if db is not None:
        # Observability must never take the feature down with it: the call has
        # already succeeded and the user is owed its result.
        try:
            db.table("ai_runs").insert({
                "user_id": user_id, "task": task, "provider": "anthropic",
                "model": served, "tokens_in": tin + cread + cwrite,
                "tokens_out": tout, "cost_usd": cost,
                "latency_ms": latency_ms, "stop_reason": stop,
            }).execute()
        except Exception as e:                                # noqa: BLE001
            print(f"[ai] ai_runs log failed ({type(e).__name__}) — "
                  f"{task} cost ${cost} went unrecorded")

    return AiResult(
        text="", model=served, tokens_in=tin, tokens_out=tout, cost_usd=cost,
        latency_ms=latency_ms, stop_reason=stop,
        served_by_fallback=served != model,
        usage_detail={"cache_read": cread, "cache_write": cwrite},
    )


def _refusal_guard(task: str, resp) -> None:
    """`stop_reason: "refusal"` arrives as a successful HTTP 200 with empty or
    partial content. Reading `content[0]` first would raise IndexError and
    surface as a 500 — an outage, for something that is not one."""
    if getattr(resp, "stop_reason", "") != "refusal":
        return
    details = getattr(resp, "stop_details", None)
    category = getattr(details, "category", None) if details else None
    print(f"[ai] {task} REFUSED by classifier (category={category})")
    raise HTTPException(
        422,
        "The AI service declined to answer that one. Your pack and its "
        "warnings are unaffected — they are computed here, not generated.",
    )


def complete(task: str, system: str, user_content: str, *,
             db=None, user_id: str | None = None,
             max_tokens: int | None = None) -> AiResult:
    """One prose answer for one task. Never returns a decision."""
    global _fallback_available

    model = _model_for(task)
    max_tokens = max_tokens or TASK_MAX_TOKENS.get(task, DEFAULT_MAX_TOKENS)
    effort = TASK_EFFORT.get(task, DEFAULT_EFFORT)
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=_system_payload(system),
        # Thinking is ON — deliberately, and not only for quality. With it
        # disabled, Opus 5 occasionally writes what should have been a tool call
        # into its visible text and leaks internal tags into the response. The
        # dial for cost is `effort` below, which is the supported one.
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user_content}],
    )

    t0 = time.monotonic()
    try:
        if _fallback_available and settings.ai_server_side_fallback:
            try:
                resp = _client().beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            except anthropic.BadRequestError as e:
                if not _mentions_fallback(e):
                    raise
                print("[ai] server-side fallback unavailable on this account — "
                      "continuing without it for the life of this process")
                _fallback_available = False
                resp = _client().messages.create(**kwargs)
        else:
            resp = _client().messages.create(**kwargs)
    except HTTPException:
        raise
    except Exception as e:                                    # noqa: BLE001
        _raise_for(task, e)

    result = _account(task, model, resp, t0, db, user_id)
    _refusal_guard(task, resp)
    result.text = "".join(b.text for b in resp.content
                          if getattr(b, "type", "") == "text").strip()
    if not result.text:
        raise HTTPException(502, "The AI service returned nothing usable.")
    return result


def _mentions_fallback(exc: anthropic.BadRequestError) -> bool:
    blob = str(exc).lower()
    return "fallback" in blob or "beta" in blob


def extract(task: str, system: str, user_content: str, schema: type, *,
            db=None, user_id: str | None = None,
            max_tokens: int | None = None) -> AiResult:
    """A validated object rather than prose — for reading race manuals (§24).

    `messages.parse` constrains the response to the pydantic schema at the API
    level and validates it here, so a malformed kit list is impossible rather
    than merely unlikely. This is the reason there is no regex fallback and no
    `json.loads` in a retry loop below it.

    NOT wrapped in server-side fallbacks: `parse` is the non-beta path, and a
    fallback model answering a schema-constrained request is a different
    reliability question than one answering prose. A refusal here is surfaced.
    """
    model = _model_for(task)
    max_tokens = max_tokens or TASK_MAX_TOKENS.get(task, DEFAULT_MAX_TOKENS)

    t0 = time.monotonic()
    try:
        resp = _client().messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=_system_payload(system),
            thinking={"type": "adaptive"},
            output_config={"effort": TASK_EFFORT.get(task, DEFAULT_EFFORT)},
            output_format=schema,
            messages=[{"role": "user", "content": user_content}],
        )
    except HTTPException:
        raise
    except Exception as e:                                    # noqa: BLE001
        _raise_for(task, e)

    result = _account(task, model, resp, t0, db, user_id)
    _refusal_guard(task, resp)
    if result.truncated:
        raise HTTPException(
            502,
            "That page was too long to read in one pass. Paste just the "
            "mandatory-equipment section instead.",
        )
    result.parsed = resp.parsed_output
    if result.parsed is None:
        raise HTTPException(502, "The AI service returned nothing usable.")
    return result


# ── generated text, stored apart from the facts it describes (§28) ───────────

def save_output(db, subject_type: str, subject_id: str, task: str,
                payload: dict, model: str) -> None:
    """Upsert into ai_outputs. Never writes to a table of facts.

    Same rule as ai_runs: a storage failure must not take down a response the
    user has already been given. It costs them a regeneration, not the answer.
    """
    try:
        db.table("ai_outputs").upsert({
            "subject_type": subject_type, "subject_id": subject_id,
            "task": task, "payload": payload, "model": model,
            "prompt_version": PROMPT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="subject_type,subject_id,task").execute()
    except Exception as e:                                    # noqa: BLE001
        print(f"[ai] ai_outputs save failed ({type(e).__name__}) for "
              f"{subject_type}/{subject_id}/{task}")


def load_output(db, subject_type: str, subject_id: str, task: str) -> dict | None:
    rows = (db.table("ai_outputs").select("*")
            .eq("subject_type", subject_type).eq("subject_id", subject_id)
            .eq("task", task).limit(1).execute().data)
    return rows[0] if rows else None
