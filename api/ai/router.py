"""The AI layer (§11, §16, §27): narrative over engine output, and Ask Outdoor.

Every endpoint here is ADDITIVE. Turn the whole router off — no key, no budget,
a refusal, a 502 from Anthropic — and the pack, the warnings, the readiness
figure and the locker are exactly what they were. Nothing in Phases 1-3 reads
anything this file writes. That is the §12 guarantee expressed as an import
graph rather than as a promise: the narrative *cannot* change a classification,
because the code that classifies does not know this module exists.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.ai import context, prompts
from api.ai_gateway import gateway
from api.core.access import owned_adventure
from api.core.auth import current_user_id
from api.core.db import get_db
from api.packing import service

router = APIRouter(prefix="/v1", tags=["ai"])

NARRATIVE_TASK = "pack_narrative"


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    #: Optional focus. With one, the answer also sees that adventure's pack.
    adventure_id: str | None = None


def _narrative_payload(stored: dict, row: dict | None) -> dict:
    """A stored narrative plus whether it still describes the current pack."""
    if not row:
        return {"narrative": None, "stale": False, "model": None,
                "prompt_version": None, "generated_at": None}
    payload = row.get("payload") or {}
    return {
        "narrative": payload.get("text"),
        # Two ways to go stale, and both are reported as one flag because the
        # user's move is the same either way: regenerate, or ignore it.
        # (1) the pack changed under it — see context.fingerprint;
        # (2) the prompt itself changed, so the text was written to different
        #     rules than the ones now in force.
        "stale": (payload.get("fingerprint") != context.fingerprint(stored)
                  or row.get("prompt_version") != gateway.PROMPT_VERSION),
        "model": row.get("model"),
        "prompt_version": row.get("prompt_version"),
        "generated_at": row.get("created_at"),
    }


@router.get("/adventures/{adventure_id}/pack/narrative")
def get_narrative(adventure_id: str, user_id: str = Depends(current_user_id)):
    """The stored paragraph. Never generates — a GET that spends money on mount
    is a GET nobody can afford to let a screen retry."""
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id)
    stored = service.read(db, adventure)
    if not stored["list"]:
        return {"narrative": None, "stale": False, "model": None,
                "prompt_version": None, "generated_at": None}
    row = gateway.load_output(db, "packing_list", stored["list"]["id"],
                              NARRATIVE_TASK)
    return _narrative_payload(stored, row)


@router.post("/adventures/{adventure_id}/pack/narrative", status_code=201)
def write_narrative(adventure_id: str, user_id: str = Depends(current_user_id)):
    """Explain the pack that already exists.

    Requires a generated pack rather than generating one: the narrative
    describes engine output, and producing both in one call would make it
    impossible to tell which of the two an unexpected sentence came from.
    """
    db = get_db()
    adventure = owned_adventure(db, adventure_id, user_id, writing=True)
    stored = service.read(db, adventure)
    if not stored["list"]:
        raise HTTPException(409, "Generate a pack for this adventure first.")

    gateway.check_budget(db, user_id)

    weather = (db.table("weather_snapshots").select("*")
               .eq("adventure_id", adventure["id"])
               .order("forecast_date").execute().data)

    result = gateway.complete(
        NARRATIVE_TASK, prompts.PACK_NARRATIVE,
        context.pack_context(adventure, stored, weather),
        db=db, user_id=user_id)

    payload = {"text": result.text, "fingerprint": context.fingerprint(stored)}
    gateway.save_output(db, "packing_list", stored["list"]["id"],
                        NARRATIVE_TASK, payload, result.model)
    return {"narrative": result.text, "stale": False, "model": result.model,
            "prompt_version": gateway.PROMPT_VERSION,
            "generated_at": None, "cost_usd": result.cost_usd}


@router.post("/ask")
def ask(body: Question, user_id: str = Depends(current_user_id)):
    """Ask Outdoor AI — grounded in this user's locker and adventures (§16).

    STATELESS, deliberately. There is no conversation to poison and no history
    to re-send: every question is answered against freshly read data. A thread
    would also mean each follow-up re-billed the whole locker, which is the
    expensive half of the prompt.
    """
    db = get_db()
    gateway.check_budget(db, user_id)

    locker = (db.table("gear_items").select("*")
              .eq("user_id", user_id).eq("status", "active").execute().data)
    adventures = (db.table("adventures").select("*")
                  .eq("user_id", user_id)
                  .order("start_date", desc=False).limit(10).execute().data)

    blocks = [context.locker_context(locker), "", context.adventures_context(adventures)]

    task = "ask_outdoor"
    if body.adventure_id:
        adventure = owned_adventure(db, body.adventure_id, user_id)
        stored = service.read(db, adventure)
        if stored["list"]:
            weather = (db.table("weather_snapshots").select("*")
                       .eq("adventure_id", adventure["id"])
                       .order("forecast_date").execute().data)
            blocks += ["", "THE PACK THEY ARE ASKING ABOUT:",
                       context.pack_context(adventure, stored, weather)]
            # A whole pack on top of a whole locker is a materially bigger
            # question, so it is routed as the deeper task rather than being
            # squeezed through a ceiling sized for a one-liner.
            task = "ask_outdoor_deep"

    blocks += ["", "THEIR QUESTION:", body.question.strip()]

    result = gateway.complete(task, prompts.ASK_OUTDOOR, "\n".join(blocks),
                              db=db, user_id=user_id)
    # NOT written to ai_outputs. That table is keyed (subject, task) and holds
    # generated text ABOUT a subject; a one-off answer to a question has no
    # subject, and storing it would evict the narrative for whatever row it was
    # forced to borrow.
    return {"answer": result.text, "model": result.model,
            "cost_usd": result.cost_usd, "grounded_in": {
                "gear_items": len(locker), "adventures": len(adventures),
                "pack": task == "ask_outdoor_deep"}}
