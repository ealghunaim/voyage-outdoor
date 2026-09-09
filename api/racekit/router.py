"""Race kit import (§24): fetch or paste, extract, then a human accepts it.

THE DRAFT IS THE WHOLE DESIGN. Mandatory kit outranks every rule in the pack
engine and marks its lines critical, so a model writing straight into an
adventure would be a model overruling the engines — the exact inversion §0.5
forbids. Instead the model produces a draft, the runner ticks the lines they
recognise from the race manual, and the ACCEPT is what confers authority.

That also makes the common failure survivable. A race page that buries the kit
in an image, or publishes three lists for three distances, produces a draft that
is visibly wrong, next to the source it came from — instead of eleven confident
critical lines on a pack list four days before the race.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from api.activities.validate import validate_adventure_attributes
from api.ai_gateway import gateway
from api.core.access import owned_adventure
from api.core.auth import current_user_id
from api.core.db import get_db
from api.packing import service
from api.racekit import extract, fetch

router = APIRouter(prefix="/v1", tags=["race-kit"])

#: A pasted kit list is a few hundred words. This bound is about a paste that
#: is actually an entire webpage's worth of text, which `narrow` then has to
#: work on anyway — it is a limit on the request body, not on the kit.
MAX_PASTE = 200_000


class DraftIn(BaseModel):
    url: str | None = None
    text: str | None = None
    #: Optional at draft time. Attaching happens on accept, and importing a kit
    #: before deciding which adventure it belongs to is an ordinary thing to do.
    adventure_id: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.url) == bool(self.text):
            raise ValueError("Give either a url or the pasted text, not both.")
        if self.text and len(self.text) > MAX_PASTE:
            raise ValueError("That paste is too long — send the equipment "
                             "section rather than the whole page.")
        return self


class AcceptIn(BaseModel):
    adventure_id: str
    #: The lines the human is actually taking, as text. Sent back rather than
    #: referenced by index: the client shows the user editable lines (a race
    #: manual PDF often needs a word fixing), and what is stored has to be what
    #: they saw, not what was extracted before they touched it.
    items: list[str] = Field(min_length=1, max_length=60)
    #: `replace` is the default because a kit list is the race's list, not a
    #: contribution to one. The previous value is kept on the import row, so
    #: replacing is reversible by reading the record.
    mode: str = "replace"


def _row(db, draft_id: str, user_id: str) -> dict:
    rows = (db.table("race_kit_imports").select("*")
            .eq("id", draft_id).eq("user_id", user_id).limit(1).execute().data)
    if not rows:
        raise HTTPException(404, "No such import.")
    return rows[0]


def _public(row: dict) -> dict:
    """What the app sees. `stats` carries cost figures and how the page was
    narrowed — ops data, not something to render beside a kit list."""
    return {k: row.get(k) for k in (
        "id", "status", "adventure_id", "source_kind", "source_url",
        "source_chars", "fetched_at", "race_name", "edition", "event",
        "extracted", "accepted_items", "accepted_at", "model", "created_at")}


@router.post("/race-kit/drafts", status_code=201)
def create_draft(body: DraftIn, user_id: str = Depends(current_user_id)):
    """Read a race page (or a paste) and return a draft kit list."""
    db = get_db()
    if body.adventure_id:
        # Checked NOW rather than at accept time. Discovering that the
        # adventure is not yours after paying for an extraction is a worse
        # sequence than discovering it before.
        owned_adventure(db, body.adventure_id, user_id, writing=True)

    gateway.check_budget(db, user_id)

    if body.url:
        fetched = fetch.fetch(body.url)
        if not extract.has_kit_signal(fetched.text):
            # Refused BEFORE the model call, and with the accurate reason. The
            # model would have answered "no equipment list on this page", which
            # sounds like a fact about the race rather than about the fetch.
            raise HTTPException(
                422,
                "That page has no equipment list in it — a lot of race sites "
                "build their pages in the browser, so there is nothing to read "
                "here. Open it and paste the equipment section instead.")
        source = {"source_kind": "url", "source_url": fetched.url,
                  "source_sha256": fetched.sha256,
                  "source_chars": len(fetched.text)}
        text, label = fetched.text, fetched.url
    else:
        source = {"source_kind": "paste", "source_url": None,
                  "source_sha256": None, "source_chars": len(body.text or "")}
        text, label = body.text or "", "pasted by the runner"

    kit, stats = extract.read_kit(text, source_label=label,
                                  db=db, user_id=user_id)

    row = db.table("race_kit_imports").insert({
        "user_id": user_id,
        "adventure_id": body.adventure_id,
        "status": "draft",
        **source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "race_name": kit.race_name,
        "edition": kit.edition,
        "event": kit.event,
        "extracted": kit.model_dump(),
        "model": stats.get("model"),
        "prompt_version": stats.get("prompt_version"),
        "stats": stats,
    }).execute().data[0]
    return _public(row)


@router.get("/race-kit/drafts")
def list_drafts(user_id: str = Depends(current_user_id)):
    db = get_db()
    rows = (db.table("race_kit_imports").select("*")
            .eq("user_id", user_id).order("created_at", desc=True)
            .limit(20).execute().data)
    return [_public(r) for r in rows]


@router.get("/race-kit/drafts/{draft_id}")
def get_draft(draft_id: str, user_id: str = Depends(current_user_id)):
    return _public(_row(get_db(), draft_id, user_id))


@router.delete("/race-kit/drafts/{draft_id}", status_code=204)
def discard_draft(draft_id: str, user_id: str = Depends(current_user_id)):
    """Marks the row discarded; does not delete it.

    What a runner rejected is as much a part of the record as what they took —
    it is the evidence that an extraction was reviewed rather than merely never
    used, and it costs one row to keep.
    """
    db = get_db()
    _row(db, draft_id, user_id)
    db.table("race_kit_imports").update({"status": "discarded"}) \
      .eq("id", draft_id).execute()


@router.post("/race-kit/drafts/{draft_id}/accept")
def accept_draft(draft_id: str, body: AcceptIn,
                 user_id: str = Depends(current_user_id)):
    """Write the accepted lines onto an adventure and rebuild its pack.

    The pack is regenerated here rather than left for the user to trigger.
    Mandatory kit changes what is REQUIRED and what is MISSING; leaving the old
    pack in place would show a list that no longer matches the race, and the
    gap between the two is exactly where someone loses an item.
    """
    if body.mode not in ("replace", "append"):
        raise HTTPException(422, "mode must be 'replace' or 'append'")

    db = get_db()
    row = _row(db, draft_id, user_id)
    adventure = owned_adventure(db, body.adventure_id, user_id, writing=True)

    lines = [line.strip() for line in body.items if line and line.strip()]
    if not lines:
        raise HTTPException(422, "Nothing to accept — every line was blank.")

    previous = list((adventure.get("attributes") or {}).get("mandatory_kit") or [])
    if body.mode == "append":
        seen = {line.lower() for line in previous}
        merged = previous + [ln for ln in lines if ln.lower() not in seen]
    else:
        merged = lines

    # Through the registry validator, exactly like any other attribute write.
    # A second path into `attributes` that skipped it would be a second set of
    # rules about what an adventure may contain (see validate.py).
    incoming = validate_adventure_attributes(
        adventure["activity_key"], {"mandatory_kit": merged}, partial=True)
    attributes = {**(adventure.get("attributes") or {}), **incoming}
    if row.get("race_name") and not attributes.get("race_name"):
        attributes.update(validate_adventure_attributes(
            adventure["activity_key"], {"race_name": row["race_name"]},
            partial=True))

    updated = (db.table("adventures").update({"attributes": attributes})
               .eq("id", adventure["id"]).execute().data)[0]

    db.table("race_kit_imports").update({
        "status": "accepted",
        "adventure_id": adventure["id"],
        "accepted_items": lines,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        # The list that was overwritten, kept so a replace is reversible by
        # reading the record rather than by remembering.
        "stats": {**(row.get("stats") or {}),
                  "mode": body.mode, "replaced": previous},
    }).eq("id", draft_id).execute()

    pack = service.generate(db, updated, user_id)
    return {"adventure": updated, "pack": pack,
            "import": _public(_row(db, draft_id, user_id))}


@router.get("/adventures/{adventure_id}/race-kit")
def adventure_provenance(adventure_id: str,
                         user_id: str = Depends(current_user_id)):
    """Where this adventure's mandatory kit came from (§24).

    A kit list without provenance is a rumour. This is what lets the pack screen
    say "from utmb.world, fetched 9 March" beside eleven critical lines — and
    what tells someone next season that they are looking at last year's edition.
    """
    db = get_db()
    owned_adventure(db, adventure_id, user_id)
    rows = (db.table("race_kit_imports").select("*")
            .eq("adventure_id", adventure_id).eq("status", "accepted")
            .order("accepted_at", desc=True).limit(1).execute().data)
    return _public(rows[0]) if rows else None
